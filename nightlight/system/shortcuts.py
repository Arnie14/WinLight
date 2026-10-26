# SPDX-License-Identifier: GPL-3.0-only
"""Keyboard shortcuts, registered with Windows and run when pressed.

As LightBulb and Twinkle Tray do it: each shortcut is registered on one
hidden window (SystemEvents) with RegisterHotKey, Windows sends WM_HOTKEY
with its id, and everything is unregistered and registered again when the
shortcuts change. Lessons from both, and from Twinkle Tray's issues:

- Whether each one is registered is kept and shown ("used by another app"
  when Windows refuses it), rather than a shortcut that silently does nothing.
- Two shortcuts with the same keys: only the first is registered, and the
  Settings page marks the others.
- A held key repeats; repeats closer than REPEAT_MS are dropped (Twinkle
  Tray: 100 ms, LightBulb: 50 ms). Switches (night light, suspend, the
  panel) are registered with MOD_NOREPEAT, so holding them doesn't flicker.
- Each press runs on its own: an action that fails is logged, and never
  blocks the next (a flag left set by an early return once disabled every
  shortcut in Twinkle Tray until a restart).
- While a shortcut is being recorded in Settings, all are unregistered:
  a registered combination never reaches the window recording it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from nightlight.core.shortcuts import MOD_NOREPEAT, REPEATING, Shortcut, parse

log = logging.getLogger(__name__)

REPEAT_MS = 100
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Each shortcut's state, as Settings shows it.
WORKS = "Works"
TAKEN = "Used by another app"
DUPLICATE = "Same keys as another shortcut"
UNAVAILABLE = "Shortcuts need Windows"
FAILED = "Windows refused it"


class ShortcutService(QObject):
    changed = Signal()  # which shortcuts are registered changed

    def __init__(self, events, run: Callable[[Shortcut], None], parent: QObject | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """`events` registers with Windows (winsystem.SystemEvents: register_hotkey,
        unregister_hotkey, hotkeyPressed); `run` does what a shortcut says."""
        super().__init__(parent)
        self._events = events
        self._run = run
        self._clock = clock
        self._shortcuts: tuple[Shortcut, ...] = ()
        self._registered: dict[int, Shortcut] = {}  # id -> shortcut
        self._status: dict[str, str] = {}  # keys -> status
        self._last_run: dict[int, float] = {}
        self._paused = False
        events.hotkeyPressed.connect(self._pressed)

    def set_shortcuts(self, shortcuts: tuple[Shortcut, ...]) -> None:
        self._shortcuts = tuple(shortcuts)
        self._apply()

    def status(self, keys: str) -> str:
        """How a shortcut stands ("Works", "Used by another app"...), "" if unknown."""
        return self._status.get(keys, "")

    def pause(self, paused: bool) -> None:
        """Let go of every shortcut while one is being recorded (the keys go to
        the recording field instead), and take them back after."""
        if paused == self._paused:
            return
        self._paused = paused
        if paused:
            self._unregister_all()
        else:
            self._apply()

    def stop(self) -> None:
        self._paused = True
        self._unregister_all()

    def _apply(self) -> None:
        self._unregister_all()
        self._status.clear()
        if self._paused:
            return
        seen: set[str] = set()
        for hotkey_id, shortcut in enumerate(self._shortcuts, 1):
            if shortcut.keys in seen:
                continue  # the first with these keys has them (the editor marks the others)
            seen.add(shortcut.keys)
            modifiers, key = parse(shortcut.keys).codes
            if shortcut.action not in REPEATING:
                modifiers |= MOD_NOREPEAT
            error = self._events.register_hotkey(hotkey_id, modifiers, key)
            if error == 0:
                self._registered[hotkey_id] = shortcut
                self._status[shortcut.keys] = WORKS
            else:
                self._status[shortcut.keys] = {ERROR_HOTKEY_ALREADY_REGISTERED: TAKEN, -1: UNAVAILABLE}.get(error, FAILED)
                log.info("Shortcut %s isn't available: %s (%s)", shortcut.keys, self._status[shortcut.keys], error)
        if self._registered:
            log.info("Shortcuts: %d registered", len(self._registered))
        self.changed.emit()

    def _unregister_all(self) -> None:
        for hotkey_id in self._registered:
            self._events.unregister_hotkey(hotkey_id)
        self._registered.clear()
        self._last_run.clear()

    def _pressed(self, hotkey_id: int) -> None:
        shortcut = self._registered.get(hotkey_id)
        if shortcut is None:
            return  # unregistered meanwhile, or another program's id
        now = self._clock()
        if now - self._last_run.get(hotkey_id, -1e9) < REPEAT_MS / 1000:
            return
        self._last_run[hotkey_id] = now
        try:
            self._run(shortcut)
        except Exception:
            log.exception("The shortcut %s failed", shortcut.keys)
