# SPDX-License-Identifier: GPL-3.0-only
"""Keyboard shortcuts: the safeguards from the 0.5.0 audit. Edge cases of the
key rules and settings, the service's lifecycle, what each action does from
every starting state, real Windows (registering, pressing, quitting), a
soak of random presses, and garbage collection and threads."""

import gc
import json
import logging
import os
import random
import subprocess
import sys
import threading
import weakref
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from nightlight import config
from nightlight.color.controller import NightLightController
from nightlight.config import AppConfig, GeneralConfig, Mode, NightLightConfig
from nightlight.core.schedule import OverrideKind
from nightlight.core.shortcuts import (
    BRIGHTNESS_DOWN,
    BRIGHTNESS_SET,
    BRIGHTNESS_UP,
    NIGHT_LIGHT,
    PANEL,
    SUSPEND,
    Shortcut,
    caution,
    parse,
    problem,
)
from nightlight.system.shortcuts import DUPLICATE, TAKEN, WORKS, ShortcutService
from tests.test_app import start  # noqa: F401  (a fixture, for app)
from tests.test_settings_window import FakeGamma
from tests.test_shortcuts import (
    DELL,
    PANEL_MONITOR,
    ROOT,
    TV,
    UP,
    Clock,
    FakeEvents,
    app,  # noqa: F401  (a fixture)
    harness,
    service,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")
# Pressing keys needs an interactive desktop; build machines (CI) have none.
real_desktop = pytest.mark.skipif(bool(os.environ.get("CI")), reason="needs a real desktop, not a CI runner")


# --- Key rules and settings ------------------------------------------------------------------


def test_alt_space_is_refused_and_altgr_combinations_are_flagged():
    """Alt+Space is every window's menu (and PowerToys Run's default), and
    Windows registers it anyway. Ctrl+Alt+letter is AltGr+letter on many
    layouts: registered, Ctrl+Alt+E stops a German keyboard typing the euro sign."""
    assert problem(parse("Alt+Space")) and not problem(parse("Ctrl+Alt+Space"))
    assert caution(parse("Ctrl+Alt+E")) and caution(parse("Ctrl+Alt+Shift+2")) and caution(parse("Ctrl+Alt+Minus"))
    for fine in ("Ctrl+Alt+Up", "Ctrl+Alt+F5", "Ctrl+Alt+Win+E", "Ctrl+Shift+E", "Alt+E", "Ctrl+Alt+Num5"):
        assert caution(parse(fine)) == "", fine
    assert Shortcut("Alt+Space", PANEL).normalized() is None  # also dropped from a hand-edited file


def test_the_altgr_warning_shows_with_the_status():
    from nightlight.ui.shortcut_editor import NOT_APPLIED, ShortcutEditor

    editor = ShortcutEditor()
    saved = (Shortcut("Ctrl+Alt+E", SUSPEND), UP)
    editor.set_shortcuts((*saved, Shortcut("Ctrl+Alt+Q", PANEL)))
    editor.show_status({"Ctrl+Alt+E": WORKS, "Ctrl+Alt+Up": WORKS}.get, saved)
    texts = [row.status.text() for row in editor.rows]
    assert texts[0].startswith(WORKS + ". ") and "AltGr" in texts[0]
    assert texts[1] == WORKS
    assert texts[2].startswith(NOT_APPLIED + ". ") and "AltGr" in texts[2]


@pytest.mark.parametrize("text", [" ctrl + ALT + up ", "Ctrl+Alt+Up", "alt+ctrl+UP", "CTRL+alt+up"])
def test_keys_parse_whatever_their_case_spacing_and_order(text):
    assert str(parse(text)) == "Ctrl+Alt+Up"
    assert parse(text) == parse("Ctrl+Alt+Up") and hash(parse(text)) == hash(parse("Ctrl+Alt+Up"))


@pytest.mark.parametrize(("qt_key", "native_vk", "written"), [
    (Qt.Key.Key_Up, 0x26, "Up"),  # NumLock off: the keypad's 8 is an arrow, and Windows sends VK_UP
    (Qt.Key.Key_8, 0x68, "Num8"),  # NumLock on
    (Qt.Key.Key_Home, 0x24, "Home"),  # NumLock off: the keypad's 7
])
def test_keypad_keys_record_as_windows_sends_them(qt_key, native_vk, written):
    """Recorded by Windows' virtual-key code, as RegisterHotKey matches it:
    with NumLock off the keypad's 8 is Up, so that's what fires it."""
    from nightlight.ui.shortcut_editor import key_name

    modifiers = Qt.KeyboardModifier.KeypadModifier
    event = QKeyEvent(QEvent.Type.KeyPress, qt_key, modifiers, 0x48, native_vk, 0)
    assert key_name(event) == written


def test_numbers_too_large_or_odd_in_settings_fall_back(tmp_path, caplog):
    """1e400 reads as infinity, which int() can't take: Winlight didn't start."""
    path = tmp_path / "settings.json"
    path.write_text('{"general": {"idle_minutes": 1e400}, "night_light": {"day_temperature": -1e400},'
                    ' "shortcuts": [{"keys": "Ctrl+Alt+Up", "action": "brightness_up", "value": 1e400},'
                    ' {"keys": "Ctrl+Alt+Down", "action": "brightness_down", "value": NaN}],'
                    ' "brightness_schedule": {"points": [{"level": 1e400, "at": "07:00"}]}}')
    loaded = config.load(path)
    assert loaded.general.idle_minutes == GeneralConfig().idle_minutes
    assert [s.value for s in loaded.shortcuts] == [10, 10]  # the default step


def test_an_unforeseen_error_reading_settings_starts_with_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"shortcuts": []}')
    monkeypatch.setattr(config, "_shortcuts_from", lambda data: 1 / 0)
    assert config.load(path) == AppConfig()
    assert (tmp_path / "settings.json.damaged").exists()  # kept for recovering by hand


def test_shortcuts_past_32_are_logged(tmp_path, caplog):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"shortcuts": [{"keys": f"Ctrl+Alt+F{n % 24 + 1}", "action": "panel"} for n in range(40)]}))
    with caplog.at_level(logging.WARNING):
        assert len(config.load(path).shortcuts) == 32
    assert "Ignoring 8 shortcuts past the first 32" in caplog.text


# --- The service --------------------------------------------------------------------------


def hotkey_message(hwnd, wparam, lparam=0, time=1):
    from ctypes import wintypes

    from nightlight.hardware.winsystem import WM_HOTKEY

    return wintypes.MSG(hWnd=hwnd, message=WM_HOTKEY, wParam=wparam, lParam=lparam, time=time)


def test_only_our_range_of_ids_reaches_the_service():
    """Windows' own ids are -1 and -2, arriving as huge unsigned numbers: they
    overflowed the signal's int inside the message filter."""
    from nightlight.hardware.winsystem import SystemEvents

    events = SystemEvents()
    events._hwnd = 0x1234
    heard = []
    events.hotkeyPressed.connect(heard.append)
    for n, (wparam, lparam) in enumerate([(0, 0), (2**64 - 1, 0), (2**64 - 2, 0), (0xC000, 0), (2**32 - 1, 0x7FFFFFFF),
                                          (1, 0x7FFFFFFF), (0xBFFF, 0)]):
        events._on_message(hotkey_message(0x1234, wparam, lparam, time=n))
    events._on_message(hotkey_message(0x9999, 5, time=99))  # another window's
    assert heard == [1, 0xBFFF]


def test_after_stop_nothing_registers_again():
    """Signing out stops the shortcuts; a recording field losing focus after
    that (Settings closing) took them back."""
    svc, events, _ran, _clock = service((UP,), answers={0x26: 1409})
    svc.stop()
    for again in (lambda: svc.pause(False), lambda: svc.set_shortcuts((UP,)), svc._retry_taken, lambda: svc.pause(True)):
        again()
        assert events.registered == {} and not svc._retry.isActive()
    events.answers[0x26] = 0
    svc._retry_taken()
    assert events.registered == {}


def test_keys_taken_aren_t_retried_while_recording():
    svc, events, _ran, _clock = service((UP,), answers={0x26: 1409})
    svc.pause(True)
    events.answers[0x26] = 0
    svc._retry_taken()
    assert events.registered == {}
    svc.pause(False)
    assert svc.status(UP.keys) == WORKS


def test_32_shortcuts_get_their_own_ids_in_windows_range():
    keys = [f"Ctrl+Alt+F{n}" for n in range(1, 25)] + [f"Ctrl+Shift+F{n}" for n in range(1, 9)]
    svc, events, _ran, _clock = service(tuple(Shortcut(k, PANEL) for k in keys))
    assert sorted(events.registered) == list(range(1, 33))
    assert all(0 < hotkey_id <= 0xBFFF for hotkey_id in events.registered)
    svc.set_shortcuts(tuple(Shortcut(k, PANEL) for k in keys[:3]))
    assert sorted(events.registered) == [1, 2, 3]  # no leftovers from the longer list


def test_the_report_says_how_each_shortcut_stands():
    shortcuts = (UP, Shortcut("Ctrl+Alt+Down", BRIGHTNESS_DOWN, 5, "DEL41A2"), Shortcut("Ctrl+Alt+Up", SUSPEND),
                 Shortcut("Win+L", PANEL))
    svc, _events, _ran, _clock = service(shortcuts, answers={0x4C: 1409})
    assert svc.report() == [
        f"Ctrl+Alt+Up: brightness_up 10%: {WORKS}",
        f"Ctrl+Alt+Down: brightness_down 5% (one display): {WORKS}",  # the display isn't named
        f"Ctrl+Alt+Up: suspend: {DUPLICATE}",
        f"Win+L: panel: {TAKEN}",
    ]
    svc.pause(True)
    assert svc.report()[0].endswith("let go while a shortcut is recorded")
    svc.stop()
    assert svc.report()[0].endswith("stopped")


def test_report_a_problem_lists_the_shortcuts(tmp_path):
    from nightlight.support import diagnostics
    from tests.test_diagnostics import sources

    src, controller = sources(tmp_path)
    src.shortcuts = lambda: [f"Win+L: panel: {TAKEN}"]
    assert f"Keyboard shortcuts:\n  Win+L: panel: {TAKEN}" in diagnostics.summary(src)
    controller.shutdown()


# --- What they do --------------------------------------------------------------------------

NOON, NIGHT = datetime(2026, 6, 15, 12, tzinfo=UTC), datetime(2026, 6, 15, 23, tzinfo=UTC)
STARTS = {
    "schedule": None,
    "activated": (OverrideKind.ACTIVATE, None),
    "suspended until resumed": (OverrideKind.SUSPEND, None),
    "suspended for an hour": (OverrideKind.SUSPEND, "timed"),
}


def controller_at(when, beginning):
    controller = NightLightController(FakeGamma(), NightLightConfig(enabled=True, mode=Mode.TIMES), lambda: when)
    if beginning is not None:
        kind, until = beginning
        controller.set_override(kind, None if until is None else when.replace(hour=(when.hour + 1) % 24))
    return controller


@pytest.mark.parametrize("when", [NOON, NIGHT], ids=["noon", "night"])
@pytest.mark.parametrize("beginning", list(STARTS))
def test_the_toggle_flips_what_shows_and_switching_back_follows_the_schedule(when, beginning):
    """From every starting state, each press flips what shows, and whenever
    what shows is what the schedule shows, no override is left behind: the
    evening still comes after switching off and on in the day (the shortcut
    and the command line share it)."""
    from nightlight.cli.commands import CommandHandler
    from nightlight.core.schedule import compute_state
    from nightlight.ui.night_light_text import is_night_light_on, toggle_night_light
    from tests.test_commands import FakeMonitors

    for toggle in (toggle_night_light, None):
        controller = controller_at(when, STARTS[beginning])
        if toggle is None:  # the command line
            handler = CommandHandler(FakeMonitors(), controller, AppConfig)
            toggle = lambda c, h=handler: h.handle({"command": "night-light", "action": "toggle"})  # noqa: E731
        scheduled_on = compute_state(controller.config, when, None, controller.zone).night_factor > 0
        for _ in range(4):
            before = is_night_light_on(controller)
            toggle(controller)
            assert is_night_light_on(controller) is not before
            if is_night_light_on(controller) == scheduled_on:
                assert controller.override is None
        controller.shutdown()


def test_the_shortcut_and_the_command_line_toggle_alike():
    from nightlight.cli.commands import CommandHandler
    from nightlight.ui.night_light_text import toggle_night_light
    from tests.test_commands import FakeMonitors

    for when in (NOON, NIGHT):
        for beginning in STARTS.values():
            ours, theirs = controller_at(when, beginning), controller_at(when, beginning)
            toggle_night_light(ours)
            CommandHandler(FakeMonitors(), theirs, AppConfig).handle({"command": "night-light", "action": "toggle"})
            assert ours.override == theirs.override
            ours.shutdown()
            theirs.shutdown()


def test_every_display_shortcuts_leave_hdr_displays_alone_unless_named():
    """A display set to no automatic DDC/CI writes in HDR tints after them
    (Twinkle Tray #1310): only a shortcut naming it changes it."""
    run, monitors, _shown = harness({"DEL41A2": 50, "BOE0812": 50}, monitors=(DELL, PANEL_MONITOR), hands_off={"DEL41A2"})
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert monitors.sent == [("BOE0812", 60)]
    run(Shortcut("Ctrl+Alt+D", BRIGHTNESS_SET, 30, "DEL41A2"))
    assert monitors.sent[-1] == ("DEL41A2", 30)


@pytest.mark.parametrize(("level", "action", "expected"), [
    (0, BRIGHTNESS_DOWN, 0),  # below the panel's minimum of 1: dimmer never raises it
    (0, BRIGHTNESS_UP, 10),
    (1, BRIGHTNESS_DOWN, 1),
    (99, BRIGHTNESS_UP, 100),
    (100, BRIGHTNESS_UP, 100),
    (5, BRIGHTNESS_DOWN, 1),
])
def test_steps_never_go_the_wrong_way(level, action, expected):
    run, monitors, shown = harness({"BOE0812": level}, monitors=(PANEL_MONITOR,))
    run(Shortcut("Ctrl+Alt+K", action, 10))
    assert monitors.levels["BOE0812"] == expected
    assert monitors.sent == ([] if expected == level else [("BOE0812", expected)])
    assert shown == [[("Built-in display", expected)]]


def test_a_set_level_below_a_tvs_minimum_stops_at_it():
    run, monitors, _shown = harness({"SAM7136": 60}, monitors=(TV,))
    run(Shortcut("Ctrl+Alt+K", BRIGHTNESS_SET, 0))
    assert monitors.sent == [("SAM7136", 20)]


def test_before_displays_are_detected_a_brightness_shortcut_does_nothing():
    run, monitors, shown = harness({}, monitors=())
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert monitors.sent == [] and shown == []


def test_a_failing_night_light_change_is_logged_and_the_next_press_works(app, monkeypatch, caplog):  # noqa: F811
    """As a gamma ramp stuck in a driver can raise."""
    events, clock = FakeEvents(), Clock()
    svc = ShortcutService(events, app._run_shortcut, clock=clock)
    svc.set_shortcuts((Shortcut("Ctrl+Alt+N", NIGHT_LIGHT),))
    real = app.controller.set_override
    calls = []

    def failing_once(kind, until=None):
        calls.append(kind)
        if len(calls) == 1:
            raise RuntimeError("the gamma ramp is busy")
        real(kind, until)

    monkeypatch.setattr(app.controller, "set_override", failing_once)
    events.hotkeyPressed.emit(1)
    clock.now += 1
    events.hotkeyPressed.emit(1)
    assert len(calls) == 2 and app.controller.override is not None and "failed" in caplog.text
    if app._shortcut_overlay:
        app._shortcut_overlay.hide()
    svc.stop()


# --- On Windows, for real --------------------------------------------------------------------

PRESSED = r"""
import ctypes, sys, time
sys.path.insert(0, sys.argv[1])
from ctypes import wintypes
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
app = QApplication([])
from nightlight.core.shortcuts import Shortcut
from nightlight.hardware import winsystem
from nightlight.system.shortcuts import ShortcutService
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]
class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]
def send(vk, up=False):
    item = INPUT(type=1)
    item.ki = KEYBDINPUT(vk, 0, 2 if up else 0, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
events = winsystem.SystemEvents(app)
ran = []
service = ShortcutService(events, ran.append)
service.set_shortcuts((Shortcut("Ctrl+Alt+Shift+F21", "brightness_up", 10),))
keys = (0x11, 0x12, 0x10, 0x84)
for vk in keys: send(vk)
for vk in reversed(keys): send(vk, up=True)
end = time.monotonic() + 1
while time.monotonic() < end:
    QCoreApplication.processEvents(); time.sleep(0.01)
service.stop()
print(len(ran))
"""


@windows_only
@real_desktop
def test_a_real_key_press_runs_the_shortcut_exactly_once():
    env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
    result = subprocess.run([sys.executable, "-c", PRESSED, str(ROOT)], capture_output=True, text=True, timeout=60, env=env)
    assert result.stdout.strip().splitlines()[-1:] == ["1"], result.stderr[-2000:]


TRY = r"""
import ctypes, sys
from ctypes import wintypes
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
ok = user32.RegisterHotKey(None, 7, int(sys.argv[1]), int(sys.argv[2]))
print(0 if ok else ctypes.get_last_error())
if ok:
    user32.UnregisterHotKey(None, 7)
"""


def try_from_another_process(keys):
    modifiers, key = parse(keys).codes
    result = subprocess.run([sys.executable, "-c", TRY, str(modifiers), str(key)], capture_output=True, text=True, timeout=30)
    return int(result.stdout.strip())


HELD = r"""
import subprocess, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from nightlight.core.shortcuts import Shortcut
from nightlight.hardware import winsystem
from nightlight.system.shortcuts import ShortcutService
def other():
    return subprocess.run([sys.executable, "-c", sys.argv[2], sys.argv[3], sys.argv[4]], capture_output=True,
                          text=True).stdout.strip()
events = winsystem.SystemEvents(app)
service = ShortcutService(events, print)
service.set_shortcuts((Shortcut("Ctrl+Alt+Shift+F20", "panel"),))
print(other())
service.stop()
print(other())
"""


@windows_only
def test_another_process_is_refused_the_keys_until_they_re_let_go():
    """In a process of its own: the tests run on Qt's offscreen platform,
    which has no window handles to register on."""
    env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
    modifiers, key = parse("Ctrl+Alt+Shift+F20").codes
    result = subprocess.run([sys.executable, "-c", HELD, str(ROOT), TRY, str(modifiers), str(key)], capture_output=True,
                            text=True, timeout=60, env=env)
    assert result.stdout.split() == ["1409", "0"], result.stdout + result.stderr[-2000:]


QUIT = r"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
import nightlight.app as app_module
from nightlight.hardware import create_backends
app_module.autostart.create = lambda: None
folder = Path(tempfile.mkdtemp())
(folder / "settings.json").write_text(json.dumps({"general": {"start_minimized": True},
    "shortcuts": [{"keys": "Ctrl+Alt+Shift+F19", "action": "panel"}, {"keys": "Ctrl+Alt+Shift+F18", "action": "suspend"}]}))
brightness, gamma = create_backends("fake")
night_light = app_module.NightLightApp(app, brightness, gamma, folder / "settings.json")
print("held", __import__("subprocess").run([sys.executable, "-c", sys.argv[2], sys.argv[3], sys.argv[4]],
      capture_output=True, text=True).stdout.strip(), flush=True)
QTimer.singleShot(300, app.quit)
app.exec()
print("quit", flush=True)
"""


@windows_only
def test_quitting_the_app_leaves_no_keys_registered():
    """The app registers its shortcuts at start and lets go of them all when
    it quits: another process can take them straight after."""
    env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
    modifiers, key = parse("Ctrl+Alt+Shift+F19").codes
    result = subprocess.run([sys.executable, "-c", QUIT, str(ROOT), TRY, str(modifiers), str(key)], capture_output=True,
                            text=True, timeout=120, env=env)
    lines = result.stdout.strip().splitlines()
    assert "held 1409" in lines and "quit" in lines, result.stdout + result.stderr[-2000:]
    assert try_from_another_process("Ctrl+Alt+Shift+F19") == 0
    assert try_from_another_process("Ctrl+Alt+Shift+F18") == 0


# --- A soak of random presses --------------------------------------------------------------


def test_ten_thousand_random_presses_settings_and_failures_leave_nothing_behind():
    """Presses (ours, unknown and repeated), recording, new settings, Windows
    refusing keys at random and actions failing at random: no exception
    escapes, what's registered always matches what Windows holds, and
    nothing grows."""
    rng = random.Random(5)
    keys = [f"Ctrl+Alt+F{n}" for n in range(1, 13)]
    events, clock = FakeEvents(), Clock()
    ran = []

    def run(shortcut):
        ran.append(shortcut)
        if rng.random() < 0.2:
            raise RuntimeError("chaos")

    svc = ShortcutService(events, run, clock=clock)
    threads = threading.active_count()
    logging.disable(logging.CRITICAL)
    try:
        for step in range(10_000):
            roll = rng.random()
            if roll < 0.70:
                events.hotkeyPressed.emit(rng.randint(-2, 40))
            elif roll < 0.80:
                svc.pause(rng.random() < 0.5)
            elif roll < 0.90:
                for key in rng.sample(range(0x70, 0x7C), 3):
                    events.answers[key] = rng.choice([0, 0, 1409, 5])
                chosen = rng.sample(keys, rng.randint(0, len(keys)))
                svc.set_shortcuts(tuple(Shortcut(k, rng.choice([BRIGHTNESS_UP, SUSPEND, PANEL])) for k in chosen))
            else:
                svc._retry_taken()
            clock.now += rng.choice([0.01, 0.05, 0.2])
            assert set(svc._registered) == set(events.registered), step
            assert set(svc._last_run) <= set(svc._registered), step
            assert not (svc._paused and events.registered), step
    finally:
        logging.disable(logging.NOTSET)
    svc.stop()
    assert events.registered == {} and svc._registered == {} and svc._taken == {}
    assert ran and threading.active_count() == threads


# --- Garbage collection and threads ----------------------------------------------------------


def test_the_service_is_freed_without_the_garbage_collector():
    """No reference cycles: the bound-method connection doesn't keep it alive,
    so it never waits for a collection (which must run on the main thread)."""
    events = FakeEvents()
    svc = ShortcutService(events, print)
    svc.set_shortcuts((UP,))
    svc.stop()
    ref, timer = weakref.ref(svc), weakref.ref(svc._retry)
    assert not gc.isenabled()  # the suite runs with automatic collection off (conftest)
    del svc  # so only reference counting can free it
    assert ref() is None and timer() is None


def test_removed_rows_are_freed_without_the_garbage_collector():
    from nightlight.ui.shortcut_editor import ShortcutEditor

    editor = ShortcutEditor()
    editor.set_shortcuts((UP, Shortcut("Ctrl+Alt+N", SUSPEND)))
    refs = [weakref.ref(row) for row in editor.rows]
    editor.rows[0].remove.click()
    editor.set_shortcuts(())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(ref() is None for ref in refs)
    ref = weakref.ref(editor)
    del editor
    assert ref() is None


def test_presses_reuse_one_note_and_make_no_new_windows(app, monkeypatch):  # noqa: F811
    from nightlight import app as app_module

    monkeypatch.setattr(app_module.winsystem, "exclusive_fullscreen", lambda: False)
    app._run_shortcut(Shortcut("Ctrl+Alt+S", SUSPEND))
    note, windows = app._shortcut_overlay, len(QApplication.topLevelWidgets())
    for _ in range(50):
        app._run_shortcut(Shortcut("Ctrl+Alt+S", SUSPEND))
    assert app._shortcut_overlay is note and len(QApplication.topLevelWidgets()) == windows
    note.hide()


class Emitter(QObject):
    hotkeyPressed = Signal(int)

    def register_hotkey(self, hotkey_id, modifiers, key):
        return 0

    def unregister_hotkey(self, hotkey_id):
        pass


def test_a_press_from_another_thread_runs_on_the_main_thread():
    """The service and its timer live on the main thread; if a press ever
    came from another thread, Qt queues it there rather than running the
    action (Qt objects, the displays) off the main thread."""
    events = Emitter()
    where = []
    svc = ShortcutService(events, lambda s: where.append(QThread.currentThread()))
    svc.set_shortcuts((UP,))
    main = QCoreApplication.instance().thread()
    assert svc.thread() is main and svc._retry.thread() is main
    worker = threading.Thread(target=lambda: events.hotkeyPressed.emit(1))
    worker.start()
    worker.join()
    assert where == []  # not run on the worker
    QCoreApplication.processEvents()
    assert where == [main]
    svc.stop()


def test_presses_add_no_threads(app):  # noqa: F811
    """Everything runs on the main thread; display and gamma calls go through
    the existing worker (started on first use, then reused), never a new one."""
    events, clock = FakeEvents(), Clock()
    svc = ShortcutService(events, app._run_shortcut, clock=clock)
    actions = (SUSPEND, NIGHT_LIGHT, BRIGHTNESS_UP, BRIGHTNESS_DOWN, PANEL)
    svc.set_shortcuts(tuple(Shortcut(f"Ctrl+Alt+F{n}", action) for n, action in enumerate(actions, 1)))

    def press_each():
        for hotkey_id in range(1, len(actions) + 1):
            clock.now += 1
            events.hotkeyPressed.emit(hotkey_id)

    press_each()  # the worker starts here if it hadn't
    before = {t.ident for t in threading.enumerate()}
    for _ in range(5):
        press_each()
    assert {t.ident for t in threading.enumerate()} <= before
    svc.stop()
    app.flyout.hide()
    if app._shortcut_overlay:
        app._shortcut_overlay.hide()
