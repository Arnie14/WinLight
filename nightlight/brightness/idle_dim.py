# SPDX-License-Identifier: GPL-3.0-only
"""Dimming every display while the PC is left alone (Twinkle Tray's "Idle
Detection"), and bringing them back on the first input.

Idle means no keyboard or mouse input for the chosen minutes. It never
counts while an app keeps the display on (video players, browsers playing
video, video calls, presentations: Windows' display-required state, the
signal they set for exactly this), while a game runs exclusive fullscreen or
Windows' presentation mode is on, or while an app the user listed is in
front (NightLightApp._idle_held). A window that merely fills the screen (a
browser or an editor in fullscreen) doesn't hold it: in beta 5 it did, so
dimming never happened with such a window in front. Music alone doesn't
hold it either: the screen isn't needed for that.

How each display is dimmed, the safe way for each:
- External displays (DDC/CI monitors, TVs, displays without control) are
  dimmed in software, a separate "idle" layer of the gamma ramp, composed
  with night light and with a TV's own software dimming. No DDC/CI writes:
  idle cycles happen several times a day, and some monitors save every
  change to their memory, or misbehave when written to unprompted.
- The laptop panel is dimmed for real through WMI, Windows' own control,
  which also saves power (Windows dims it the same way when idle).
- HDR displays ignore gamma ramps, so they're dimmed through Windows' SDR
  content brightness where that is their control (also Windows' own,
  nothing sent to the display), and otherwise left alone.

Safety rules:
- Dimming only ever lowers a display, never brightens one already below
  the idle level, and leaves hidden displays alone.
- Laptop panels and SDR levels go through MonitorManager.restore_brightness:
  not the user's choice (not remembered), skipped if asleep.
- Coming back, each display gets the level it should have now, by the same
  rule as restores and the brightness schedule (BrightnessMemory.target), so
  a schedule step that passed while away isn't undone; else its level
  before dimming. While dimmed, the schedule and restores hold off, so
  nothing brightens an idle screen.
- Quitting while dimmed puts the levels back first.

Windows' own screen timeout (its power plan's "dim display" and "turn off
display" times, read only): Windows turned the screen off with Winlight's
dimming still on, and brought it back at that dimmed level; a laptop panel
then stayed dim for seconds after waking, as nothing is sent to a display
until it is detected again. So the dimming is undone WINDOWS_LEAD_S before
Windows dims or turns the screen off, and the screen goes dark, and comes
back, at its usual level; it isn't dimmed again until input. Where Windows
would get there first, it isn't dimmed at all: it would only be undone.
While the PC is locked, the lock screen's own timeout counts too (Windows
turns the screen off a minute after locking, or after the last input there).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from nightlight.brightness.memory import BrightnessMemory
from nightlight.brightness.monitors import IDLE, RESTORE, MonitorManager

log = logging.getLogger(__name__)

CHECK_MS = 5000  # while waiting to dim
WATCH_MS = 300  # while dimmed: notice input quickly
# The software layer fades in these steps (the hardware ones fade by themselves).
FADE_STEPS = 8
FADE_STEP_MS = 60
# Undone this long before Windows dims or turns the screen off: room for the
# hardware fade, and for a check (every WATCH_MS) to come round.
WINDOWS_LEAD_S = 8.0
WINDOWS_READ_S = 5.0  # Windows' timeouts are read again at most this often
# Not dimmed at all if it would last less than this before being undone for
# Windows: a screen dimmed for a few seconds, then brightened, looks broken.
MIN_DIMMED_S = 30.0


class IdleDimmer(QObject):
    def __init__(
        self,
        monitors: MonitorManager,
        memory: BrightnessMemory,
        idle_seconds: Callable[[], float],
        keeps_display_on: Callable[[], bool],
        hidden: Callable[[], frozenset[str]] = frozenset,
        gamma=None,  # a gamma backend with set_idle_dim, for software dimming
        parent: QObject | None = None,
        scheduler=None,  # the brightness schedule, held back while dimmed like restores
        # winsystem.screen_timeouts: (dim, off, lock screen off) in seconds, None for never
        windows_timeouts: Callable[[], tuple[int | None, int | None, int | None]] = lambda: (None, None, None),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._monitors = monitors
        self._memory = memory
        self._idle_seconds = idle_seconds
        self._keeps_display_on = keeps_display_on
        self._hidden = hidden
        self._enabled = False
        self._after_s = 300.0
        self._level = 20
        self._gamma = gamma if hasattr(gamma, "set_idle_dim") else None
        self._scheduler = scheduler
        self._windows_timeouts = windows_timeouts
        self._clock = clock
        self._windows: tuple[float, tuple[int | None, int | None, int | None]] | None = None  # (read at, timeouts)
        self._locked_at: float | None = None  # when the PC was locked (the clock's time), while locked
        self._handed_over = False  # undone for Windows' timeout: not dimmed again until input
        self._before: dict[str, int] | None = None  # display key -> level before dimming, while dimmed
        self._software: list[str] = []  # displays dimmed in software, while dimmed
        self._fade: list[dict[str, int]] = []  # software levels still to apply, one per step
        self._fade_timer = QTimer(self, interval=FADE_STEP_MS)
        self._fade_timer.timeout.connect(self._fade_step)
        self._timer = QTimer(self, interval=CHECK_MS)
        self._timer.timeout.connect(self.check)

    @property
    def dimmed(self) -> bool:
        return self._before is not None

    def plan(self) -> tuple[dict[str, int], list[str]]:
        """Which displays to dim, and how: (display key -> hardware/SDR level for the
        laptop panel and SDR-controlled HDR displays, never brighter than now),
        [GDI names to dim in software]."""
        hidden = self._hidden()
        levels, software = {}, []
        for monitor in self._monitors.monitors:
            if monitor.key in hidden:
                continue
            current = self._monitors.value(monitor.key)
            if monitor.supported and ((monitor.internal and monitor.control == "hardware") or monitor.control == "sdr"):
                target = max(monitor.minimum, self._level)
                if current is not None and target < current:
                    levels[monitor.key] = target
            elif (not monitor.hdr and not monitor.internal and monitor.display and self._gamma is not None
                  and monitor.display not in software):  # cloned displays share one ramp: once
                software.append(monitor.display)
        return levels, software

    def configure(self, enabled: bool, minutes: int, level: int) -> None:
        self._enabled = enabled
        self._after_s = max(1, min(240, minutes)) * 60
        self._level = max(0, min(100, level))
        if enabled:
            self._timer.start(WATCH_MS if self.dimmed else CHECK_MS)
        else:
            self._timer.stop()
            self.wake()

    def check(self) -> None:
        idle = self._idle_seconds()
        if idle < self._after_s:
            self._handed_over = False  # input again: dimming may come back
        if self.dimmed:
            if idle < self._after_s:
                self.wake()
            elif (windows := self.windows_in(idle)) is not None and windows <= WINDOWS_LEAD_S:
                log.info("Windows dims or turns the screen off in %s; bringing displays back first, so they come back at "
                         "their usual level", duration(max(0.0, windows)))
                self._handed_over = True
                self.wake(why="")
        elif self._enabled and not self._handed_over and idle >= self._after_s and not self._keeps_display_on():
            if (windows := self.windows_in(idle)) is not None and windows <= WINDOWS_LEAD_S + MIN_DIMMED_S:
                self._handed_over = True  # Windows gets there first: dimming now would only be undone
                log.info("Not dimming: Windows dims or turns the screen off in %s", duration(max(0.0, windows)))
            else:
                self._dim(idle)

    def on_locked(self) -> None:
        """The PC was locked: the lock screen's own timeout counts from now."""
        if self._locked_at is None:
            self._locked_at = self._clock()

    def on_unlocked(self) -> None:
        self._locked_at = None

    def windows_in(self, idle: float) -> float | None:
        """Seconds until Windows first dims or turns off the screen, by its
        power plan (and, while locked, the lock screen's timeout, counted from
        the lock or the last input there, whichever came later); None for
        never or not known."""
        dim, off, locked = self._read_windows()
        left = [after - idle for after in (dim, off) if after]
        if locked and self._locked_at is not None:
            left.append(locked - min(idle, self._clock() - self._locked_at))
        return min(left) if left else None

    def _read_windows(self) -> tuple[int | None, int | None, int | None]:
        now = self._clock()
        if self._windows is None or now - self._windows[0] >= WINDOWS_READ_S:
            try:
                dim, off, locked = self._windows_timeouts()
            except Exception:  # a failure here must never stop idle dimming
                log.debug("Could not read Windows' screen timeouts", exc_info=True)
                dim = off = locked = None
            self._windows = (now, (dim, off, locked))
        return self._windows[1]

    def wake(self, why: str = "Input again") -> None:
        """Input again (or the feature turned off, or quitting, or Windows'
        timeout coming): bring every display back."""
        if self._before is None:
            return
        before, self._before = self._before, None
        self._memory.set_held(False)
        if why:
            log.info("%s; bringing displays back from idle dimming", why)
        for monitor in self._monitors.monitors:
            if monitor.key in before:
                level = self._memory.target(monitor)
                self._monitors.restore_brightness(monitor.key, before[monitor.key] if level is None else level, fade=True, source=RESTORE)
        if self._scheduler is not None:
            # After the restores: a point that began while away replaces them in the queue.
            self._scheduler.set_held(False)
        self._fade_software(self._level, 100, self._software)
        self._software = []
        if self._enabled:
            self._timer.start(CHECK_MS)

    def release(self) -> None:
        """Quitting: undo at once, without fading, and stop watching (wake()
        starts the idle check again, which could dim after signing out began)."""
        self._fade_timer.stop()
        self._fade = []
        if self.dimmed:
            self.wake()
        self._enabled = False
        self._timer.stop()
        self._fade_timer.stop()
        if self._gamma is not None:
            self._gamma.set_idle_dim({})

    def _dim(self, idle: float) -> None:
        levels, software = self.plan()
        if not levels and not software:
            return
        log.info(
            "No input for %.0f min; dimming to %d%%: %d display(s) in software, %d through Windows",
            idle / 60, self._level, len(software), len(levels),
        )
        self._before = {key: self._monitors.value(key) for key in levels}
        for key, level in levels.items():
            self._monitors.restore_brightness(key, level, fade=True, source=IDLE)
        self._software = software
        self._fade_software(100, self._level, software)
        self._memory.set_held(True)
        if self._scheduler is not None:
            self._scheduler.set_held(True)
        self._timer.start(WATCH_MS)

    def _fade_software(self, start: int, end: int, displays: list[str]) -> None:
        if self._gamma is None or not displays:
            return
        steps = [round(start + (end - start) * i / FADE_STEPS) for i in range(1, FADE_STEPS + 1)]
        self._fade = [dict.fromkeys(displays, level) if level < 100 else {} for level in steps]
        self._fade_timer.start()
        self._fade_step()

    def _fade_step(self) -> None:
        if not self._fade:
            self._fade_timer.stop()
            return
        self._gamma.set_idle_dim(self._fade.pop(0))


def duration(seconds: float) -> str:
    """600 -> "10 min", 885 -> "14 min 45 s", 45 -> "45 s", 7200 -> "2 h"."""
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours} h"] * bool(hours) + [f"{minutes} min"] * bool(minutes) + [f"{secs} s"] * bool(secs)
    return " ".join(parts) or "0 s"
