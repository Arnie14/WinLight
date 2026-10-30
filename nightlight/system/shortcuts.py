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
- Keys another app has are tried again every RETRY_MS, so a shortcut lost to
  an app that started first at sign-in works once that app quits.
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

from PySide6.QtCore import QObject, QTimer, Signal

from nightlight.core.shortcuts import MOD_NOREPEAT, REPEATING, WITH_VALUE, Shortcut, parse

log = logging.getLogger(__name__)

REPEAT_MS = 100
RETRY_MS = 30_000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Each shortcut's state, as Settings shows it.
WORKS = "Works"
TAKEN = "Windows or another app has these keys"  # ERROR_HOTKEY_ALREADY_REGISTERED: Win+L is Windows'
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
        self._taken: dict[int, Shortcut] = {}  # id -> shortcut whose keys another app has
        self._paused = False
        self._stopped = False  # quitting: nothing registers again, whatever asks
        self._retry = QTimer(self, interval=RETRY_MS)
        self._retry.timeout.connect(self._retry_taken)
        events.hotkeyPressed.connect(self._pressed)

    def set_shortcuts(self, shortcuts: tuple[Shortcut, ...]) -> None:
        self._shortcuts = tuple(shortcuts)
        self._apply()

    def status(self, keys: str) -> str:
        """How a shortcut stands ("Works", "Used by another app"...), "" if unknown."""
        return self._status.get(keys, "")

    def report(self) -> list[str]:
        """Each shortcut and how it stands, for Report a Problem: a failure is
        never only in Settings. Displays aren't named (a custom name may be personal)."""
        lines, seen = [], set()
        for shortcut in self._shortcuts:
            if shortcut.keys in seen:
                state = DUPLICATE
            elif self._stopped:
                state = "stopped"
            elif self._paused:
                state = "let go while a shortcut is recorded"
            else:
                state = self._status.get(shortcut.keys, "not registered")
            seen.add(shortcut.keys)
            amount = f" {shortcut.value}%" if shortcut.action in WITH_VALUE else f" {shortcut.levels}" if shortcut.levels else ""
            target = " (one display)" if shortcut.display else ""
            lines.append(f"{shortcut.keys}: {shortcut.action}{amount}{target}: {state}")
        return lines

    def pause(self, paused: bool) -> None:
        """Let go of every shortcut while one is being recorded (the keys go to
        the recording field instead), and take them back after."""
        if paused == self._paused or self._stopped:
            return
        self._paused = paused
        if paused:
            self._unregister_all()
        else:
            self._apply()

    def stop(self) -> None:
        """Let go of every shortcut for good (quitting, signing out): a
        recording field losing focus afterwards doesn't take them back."""
        self._stopped = self._paused = True
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
            error = self._register(hotkey_id, shortcut)
            if error == 0:
                continue
            self._status[shortcut.keys] = {ERROR_HOTKEY_ALREADY_REGISTERED: TAKEN, -1: UNAVAILABLE}.get(error, FAILED)
            log.info("Shortcut %s isn't available: %s (%s)", shortcut.keys, self._status[shortcut.keys], error)
            if error == ERROR_HOTKEY_ALREADY_REGISTERED:
                self._taken[hotkey_id] = shortcut
        if self._registered:
            log.info("Shortcuts: %d registered", len(self._registered))
        if self._taken:
            self._retry.start()
        self.changed.emit()

    def _register(self, hotkey_id: int, shortcut: Shortcut) -> int:
        modifiers, key = parse(shortcut.keys).codes
        if shortcut.action not in REPEATING:
            modifiers |= MOD_NOREPEAT
        error = self._events.register_hotkey(hotkey_id, modifiers, key)
        if error == 0:
            self._registered[hotkey_id] = shortcut
            self._status[shortcut.keys] = WORKS
        return error

    def _retry_taken(self) -> None:
        if self._paused:
            return
        for hotkey_id, shortcut in list(self._taken.items()):
            if self._register(hotkey_id, shortcut) == 0:
                del self._taken[hotkey_id]
                log.info("Shortcut %s is free again and registered", shortcut.keys)
                self.changed.emit()
        if not self._taken:
            self._retry.stop()

    def _unregister_all(self) -> None:
        for hotkey_id in self._registered:
            self._events.unregister_hotkey(hotkey_id)
        self._registered.clear()
        self._taken.clear()
        self._retry.stop()
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
