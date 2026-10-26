# SPDX-License-Identifier: GPL-3.0-only
"""Keyboard shortcuts, from the key rules to the Settings page. Twinkle Tray's
issues are cited where a test guards against one of its bugs."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest

from nightlight import config
from nightlight.config import AppConfig, DisplayPrefs, GeneralConfig
from nightlight.core.shortcuts import (
    BRIGHTNESS_DOWN,
    BRIGHTNESS_SET,
    BRIGHTNESS_UP,
    MOD_NOREPEAT,
    NIGHT_LIGHT,
    PANEL,
    SUSPEND,
    Shortcut,
    parse,
    problem,
)
from nightlight.hardware.brightness import MonitorInfo
from nightlight.system.shortcuts import FAILED, TAKEN, UNAVAILABLE, WORKS, ShortcutService
from tests.test_app import start  # noqa: F401  (a fixture, for app)

ROOT = Path(__file__).resolve().parent.parent

# --- Which keys, and how they're written ------------------------------------------


@pytest.mark.parametrize(("text", "written", "codes"), [
    ("ctrl + alt + up", "Ctrl+Alt+Up", (0x0003, 0x26)),
    ("Alt+Ctrl+Up", "Ctrl+Alt+Up", (0x0003, 0x26)),  # one way of writing each
    ("F13", "F13", (0, 0x7C)),
    ("Win+Shift+F24", "Shift+Win+F24", (0x000C, 0x87)),
    ("Ctrl+Num5", "Ctrl+Num5", (0x0002, 0x65)),
])
def test_combinations_are_read_and_written_one_way(text, written, codes):
    chord = parse(text)
    assert str(chord) == written and chord.codes == codes
    assert parse(written) == chord


@pytest.mark.parametrize("text", [
    "", "Ctrl", "Ctrl+", "+A", "O+Num8",  # two ordinary keys: Windows would fire on the second alone (#162)
    "Ctrl+Ctrl+A", "Hyper+A", "Ctrl+Pause",  # Pause can't be registered (#541)
])
def test_what_isnt_a_combination_is_refused(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize(("text", "allowed"), [
    ("A", False), ("Shift+A", False), ("Shift+1", False), ("Space", False), ("Enter", False), ("Shift+Tab", False),
    ("Delete", False),  # keys for typing, as in LightBulb's HotKeyTextBox
    ("Ctrl+A", True), ("Alt+1", True), ("Win+Num5", True), ("Ctrl+Space", True),
    ("F13", True), ("PageUp", True), ("Shift+F5", True),  # keys that don't type may stand alone
])
def test_keys_that_type_need_ctrl_alt_or_win(text, allowed):
    assert (problem(parse(text)) == "") is allowed


def test_a_shortcut_is_kept_only_if_it_can_be_used():
    assert Shortcut("ctrl+alt+up", BRIGHTNESS_UP, 250).normalized() == Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 100)
    assert Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 0).normalized().value == 1  # a step of nothing isn't one
    assert Shortcut("Ctrl+Alt+Up", BRIGHTNESS_SET, 0).normalized().value == 0  # off is a level
    assert Shortcut("A").normalized() is None
    assert Shortcut("Ctrl+A", "explode").normalized() is None
    assert Shortcut("").normalized() is None


# --- In the settings file ----------------------------------------------------------


def test_shortcuts_are_saved_and_unusable_ones_dropped_on_load(tmp_path):
    path = tmp_path / "settings.json"
    shortcuts = (Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 5), Shortcut("F13", BRIGHTNESS_SET, 40, "DEL41A2"))
    config.save(AppConfig(shortcuts=shortcuts, general=GeneralConfig(shortcut_overlay=False)), path)
    loaded = config.load(path)
    assert loaded.shortcuts == shortcuts and not loaded.general.shortcut_overlay
    data = json.loads(path.read_text())
    data["shortcuts"] += [{"keys": "A"}, {"keys": "Ctrl+B", "action": "nope"}, "garbage", {"keys": "Ctrl+Alt+N", "action": SUSPEND}]
    path.write_text(json.dumps(data))
    assert [s.keys for s in config.load(path).shortcuts] == ["Ctrl+Alt+Up", "F13", "Ctrl+Alt+N"]
    data["shortcuts"] = {"not": "a list"}
    path.write_text(json.dumps(data))
    assert config.load(path).shortcuts == ()


def test_at_most_32_shortcuts_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"shortcuts": [{"keys": f"Ctrl+Alt+F{1 + n % 24}"} for n in range(50)]}))
    assert len(config.load(path).shortcuts) == config.MAX_SHORTCUTS


# --- Registering and running ----------------------------------------------------------


class FakeEvents(QObject):
    """SystemEvents' shortcut part: answers per key code, like Windows."""

    hotkeyPressed = Signal(int)

    def __init__(self, answers=None):
        super().__init__()
        self.answers = answers or {}
        self.registered: dict[int, tuple[int, int]] = {}
        self.calls = []

    def register_hotkey(self, hotkey_id, modifiers, key):
        self.calls.append(("register", hotkey_id, modifiers, key))
        answer = self.answers.get(key, 0)
        if answer == 0:
            assert hotkey_id not in self.registered, "an id registered twice"
            self.registered[hotkey_id] = (modifiers, key)
        return answer

    def unregister_hotkey(self, hotkey_id):
        self.calls.append(("unregister", hotkey_id))
        self.registered.pop(hotkey_id, None)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def service(shortcuts, answers=None):
    events, ran, clock = FakeEvents(answers), [], Clock()
    svc = ShortcutService(events, ran.append, clock=clock)
    svc.set_shortcuts(shortcuts)
    return svc, events, ran, clock


UP = Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10)
DOWN = Shortcut("Ctrl+Alt+Down", BRIGHTNESS_DOWN, 10)
TOGGLE = Shortcut("Ctrl+Alt+N", SUSPEND)


def test_each_shortcut_is_registered_and_switches_dont_repeat_when_held():
    _svc, events, _ran, _clock = service((UP, TOGGLE))
    assert events.registered == {1: (0x0003, 0x26), 2: (0x0003 | MOD_NOREPEAT, ord("N"))}


def test_what_windows_says_is_shown_for_each():
    shortcuts = (UP, Shortcut("Ctrl+Alt+Down", BRIGHTNESS_DOWN), Shortcut("Ctrl+Alt+F5"), Shortcut("Ctrl+Alt+Up", BRIGHTNESS_DOWN))
    svc, events, _ran, _clock = service(shortcuts, answers={0x28: 1409, 0x74: 5})
    assert svc.status("Ctrl+Alt+Up") == WORKS
    assert svc.status("Ctrl+Alt+Down") == TAKEN  # another app has it
    assert svc.status("Ctrl+Alt+F5") == FAILED
    assert list(events.registered) == [1]  # the second Ctrl+Alt+Up wasn't tried: same keys
    svc2, _events, _ran, _clock = service((UP, Shortcut("Ctrl+Alt+Up", BRIGHTNESS_SET, 50)))
    assert svc2.status("Ctrl+Alt+Up") == WORKS  # the first keeps its status (the editor marks the second)
    assert ShortcutService(FakeEvents({0x26: -1}), print).status("x") == ""
    svc3, _events, _ran, _clock = service((UP,), answers={0x26: -1})
    assert svc3.status("Ctrl+Alt+Up") == UNAVAILABLE


def test_changing_shortcuts_lets_go_of_the_old_ones_first():
    svc, events, _ran, _clock = service((UP, DOWN))
    svc.set_shortcuts((TOGGLE,))
    assert events.registered == {1: (0x0003 | MOD_NOREPEAT, ord("N"))}
    assert [c[0] for c in events.calls[2:]] == ["unregister", "unregister", "register"]


def test_a_press_runs_its_shortcut_and_others_are_ignored():
    svc, events, ran, clock = service((UP, DOWN))
    events.hotkeyPressed.emit(2)
    events.hotkeyPressed.emit(99)  # not ours
    assert ran == [DOWN]
    svc.set_shortcuts(())
    clock.now += 1
    events.hotkeyPressed.emit(2)  # a press queued before it was let go
    assert ran == [DOWN]


def test_a_held_key_repeats_at_most_every_100_ms():
    _svc, events, ran, clock = service((UP,))
    for _ in range(5):  # the keyboard's auto-repeat, about every 33 ms
        events.hotkeyPressed.emit(1)
        clock.now += 0.033
    assert len(ran) == 2  # at 0 and at 132 ms
    clock.now += 0.1
    events.hotkeyPressed.emit(1)
    assert len(ran) == 3


def test_a_failing_action_never_blocks_the_next_press(caplog):
    """Twinkle Tray once left a flag set on an early return, and every
    hotkey stopped working until a restart."""
    events, clock, calls = FakeEvents(), Clock(), []

    def run(shortcut):
        calls.append(shortcut)
        if len(calls) == 1:
            raise RuntimeError("a display went away mid-change")

    svc = ShortcutService(events, run, clock=clock)
    svc.set_shortcuts((UP,))
    events.hotkeyPressed.emit(1)
    clock.now += 1
    events.hotkeyPressed.emit(1)
    assert len(calls) == 2 and "failed" in caplog.text


def test_while_recording_every_shortcut_is_let_go_and_taken_back_after():
    svc, events, ran, clock = service((UP, TOGGLE))
    svc.pause(True)
    assert events.registered == {}
    events.hotkeyPressed.emit(1)
    assert ran == []
    svc.pause(True)  # twice: nothing more
    svc.set_shortcuts((UP,))  # applied while recording: registered once recording ends
    assert events.registered == {}
    svc.pause(False)
    assert events.registered == {1: (0x0003, 0x26)}
    clock.now += 1
    events.hotkeyPressed.emit(1)
    assert ran == [UP]
    svc.stop()
    assert events.registered == {}


# --- What they do ---------------------------------------------------------------------------


class FakeMonitors:
    """MonitorManager as shortcuts use it."""

    def __init__(self, monitors, levels, controllable=None):
        self.monitors = monitors
        self.levels = dict(levels)
        self.controllable = controllable or {}
        self.sent = []

    def state(self, key):
        return types.SimpleNamespace(controllable=self.controllable.get(key, True))

    def value(self, key):
        return self.levels.get(key)

    def set_brightness(self, key, value, source="user", fade=False):
        self.sent.append((key, value))
        self.levels[key] = value


DELL = MonitorInfo(0, "DELL U2720Q", True, key="DEL41A2")
PANEL_MONITOR = MonitorInfo(1, "Built-in display", True, key="BOE0812", internal=True, minimum=1)
TV = MonitorInfo(2, "Living room TV", True, key="SAM7136", minimum=20)
OLD = MonitorInfo(3, "Old projector", False, key="EPS0000")


def harness(levels, displays=(), controllable=None, monitors=(DELL, PANEL_MONITOR, TV, OLD)):
    from nightlight.app import NightLightApp

    shown = []
    app = types.SimpleNamespace(
        monitors=FakeMonitors(list(monitors), levels, controllable), _config=AppConfig(displays=tuple(displays)),
        _show_shortcut_result=lambda levels=None, message="": shown.append(levels or message))
    return (lambda shortcut: NightLightApp._shortcut_brightness(app, shortcut)), app.monitors, shown


def test_brighter_moves_every_display_by_the_step_keeping_their_difference():
    """Twinkle Tray #716: with several displays, each keeps its own level."""
    run, monitors, shown = harness({"DEL41A2": 50, "BOE0812": 70, "SAM7136": 95})
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert monitors.sent == [("DEL41A2", 60), ("BOE0812", 80), ("SAM7136", 100)]
    assert shown == [[("DELL U2720Q", 60), ("Built-in display", 80), ("Living room TV", 100)]]


def test_held_down_each_step_starts_from_the_level_last_set():
    """Twinkle Tray #60: levels jumped around when steps started from stale readings."""
    run, monitors, _shown = harness({"DEL41A2": 50}, monitors=(DELL,))
    for _ in range(3):
        run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert monitors.sent == [("DEL41A2", 60), ("DEL41A2", 70), ("DEL41A2", 80)]


def test_steps_stop_at_each_displays_own_limits():
    run, monitors, shown = harness({"DEL41A2": 3, "BOE0812": 5, "SAM7136": 25})
    run(Shortcut("Ctrl+Alt+Down", BRIGHTNESS_DOWN, 10))
    assert monitors.sent == [("DEL41A2", 0), ("BOE0812", 1), ("SAM7136", 20)]
    monitors.sent.clear()
    run(Shortcut("Ctrl+Alt+Down", BRIGHTNESS_DOWN, 10))
    assert monitors.sent == []  # already at the bottom: nothing sent
    assert shown[-1] == [("DELL U2720Q", 0), ("Built-in display", 1), ("Living room TV", 20)]  # but shown


def test_one_display_by_its_key_and_a_set_level():
    run, monitors, _shown = harness({"DEL41A2": 50, "BOE0812": 70, "SAM7136": 90})
    run(Shortcut("F13", BRIGHTNESS_SET, 40, "BOE0812"))
    assert monitors.sent == [("BOE0812", 40)]
    run(Shortcut("F14", BRIGHTNESS_SET, 0))
    assert monitors.sent[1:] == [("DEL41A2", 0), ("BOE0812", 1), ("SAM7136", 20)]  # each display's own minimum


def test_hidden_unreachable_and_unknown_displays_are_left_alone():
    run, monitors, shown = harness({"DEL41A2": 50, "BOE0812": None, "SAM7136": 50},
                                   displays=(DisplayPrefs("SAM7136", hidden=True),), controllable={"DEL41A2": False})
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert monitors.sent == [] and shown == []  # asleep, unknown level, hidden; the projector has no control
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10, "NOT-CONNECTED"))
    assert monitors.sent == []


def test_custom_names_are_shown():
    run, _monitors, shown = harness({"DEL41A2": 50}, displays=(DisplayPrefs("DEL41A2", "Left"),), monitors=(DELL,))
    run(Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 10))
    assert shown == [[("Left", 60)]]


# --- In the running app -------------------------------------------------------------------------


def active(widget):
    """Shown and active, so it can take keyboard focus (offscreen too)."""
    widget.show()
    widget.activateWindow()
    QTest.qWaitForWindowActive(widget)
    return widget


@pytest.fixture
def app(request, monkeypatch):
    from nightlight import app as app_module

    monkeypatch.setattr(app_module.winsystem, "exclusive_fullscreen", lambda: False)
    night_light, _ = request.getfixturevalue("start")(GeneralConfig())
    return night_light




def test_night_light_and_suspend_switch_and_say_so(app):
    from nightlight.core.schedule import OverrideKind

    app._run_shortcut(Shortcut("Ctrl+Alt+N", NIGHT_LIGHT))
    assert app.controller.override.kind is OverrideKind.ACTIVATE  # it was off: on until changed back
    assert app._shortcut_overlay.isVisible() and app._shortcut_overlay._message.startswith("Night light:")
    app._run_shortcut(Shortcut("Ctrl+Alt+N", NIGHT_LIGHT))
    assert app.controller.override.kind is OverrideKind.SUSPEND
    app._run_shortcut(Shortcut("Ctrl+Alt+S", SUSPEND))
    assert app.controller.override is None  # resumed
    app._run_shortcut(Shortcut("Ctrl+Alt+S", SUSPEND))
    assert app.controller.override.kind is OverrideKind.SUSPEND and app.controller.override.until is None
    app._shortcut_overlay.hide()


def test_the_panel_shortcut_opens_the_panel_unless_a_game_is_fullscreen(app, monkeypatch):
    opened = []
    monkeypatch.setattr(app, "_open_flyout", lambda anchor=None: opened.append(True))
    app._run_shortcut(Shortcut("Ctrl+Alt+P", PANEL))
    assert opened == [True]
    monkeypatch.setattr(app, "_busy", lambda what: True)
    app._run_shortcut(Shortcut("Ctrl+Alt+P", PANEL))
    assert opened == [True]


@pytest.mark.parametrize("reason", ["off", "panel open", "exclusive fullscreen"])
def test_the_overlay_stays_away_when_it_should(app, monkeypatch, reason):
    from dataclasses import replace

    from nightlight import app as app_module

    if reason == "off":
        app._config = replace(app._config, general=replace(app._config.general, shortcut_overlay=False))
    elif reason == "panel open":
        monkeypatch.setattr(app.flyout, "isVisible", lambda: True)
    else:
        monkeypatch.setattr(app_module.winsystem, "exclusive_fullscreen", lambda: True)  # Twinkle Tray #83
    app._run_shortcut(Shortcut("Ctrl+Alt+N", NIGHT_LIGHT))
    assert app._shortcut_overlay is None


def test_applied_shortcuts_are_registered_and_shown_in_settings(app):
    events = FakeEvents()
    app.shortcuts = ShortcutService(events, app._run_shortcut)
    app.show_settings()
    app.shortcuts.changed.connect(app._settings.refresh_shortcut_status)
    app._settings.shortcut_editor._add(UP)
    row = app._settings.shortcut_editor.rows[-1]
    assert row.status.text() == "Click Apply to use it"
    app._settings._apply()
    assert events.registered == {1: (0x0003, 0x26)}
    assert row.status.text() == WORKS
    app._settings.close()


# --- Recording keys ------------------------------------------------------------------------------


@pytest.fixture
def recorder():
    from nightlight.ui.shortcut_editor import KeyRecorder

    field = active(KeyRecorder())
    field.setFocus()
    yield field
    field.hide()


CTRL_ALT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier


@pytest.mark.parametrize(("key", "modifiers", "written"), [
    (Qt.Key.Key_Up, CTRL_ALT, "Ctrl+Alt+Up"),
    (Qt.Key.Key_F13, Qt.KeyboardModifier.NoModifier, "F13"),
    (Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, "Ctrl+Shift+N"),
    (Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.KeypadModifier, "Alt+Num5"),
    (Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier, "Ctrl+Tab"),
    (Qt.Key.Key_Up, Qt.KeyboardModifier.MetaModifier, "Win+Up"),
])
def test_pressed_keys_are_recorded(recorder, key, modifiers, written):
    QTest.keyClick(recorder, key, modifiers)
    assert recorder.text() == written


@pytest.mark.parametrize(("key", "modifiers"), [
    (Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier),
    (Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier),
    (Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier),
    (Qt.Key.Key_Pause, Qt.KeyboardModifier.ControlModifier),  # #541
    (Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier),  # a modifier alone: waits for a key
])
def test_keys_for_typing_and_unusable_keys_are_refused(recorder, key, modifiers):
    refused = []
    recorder.refused.connect(refused.append)
    QTest.keyClick(recorder, Qt.Key.Key_Up, CTRL_ALT)
    QTest.keyClick(recorder, key, modifiers)
    assert recorder.text() == "Ctrl+Alt+Up"
    assert bool(refused) is (key != Qt.Key.Key_Control)


def test_tab_is_recorded_rather_than_moving_on(recorder):
    QTest.keyClick(recorder, Qt.Key.Key_Tab)
    assert recorder.hasFocus() and recorder.text() == ""  # refused (it types), but focus stayed


@pytest.mark.parametrize("key", [Qt.Key.Key_Escape, Qt.Key.Key_Backspace, Qt.Key.Key_Delete])
def test_esc_backspace_or_delete_clear_it(recorder, key):
    QTest.keyClick(recorder, Qt.Key.Key_Up, CTRL_ALT)
    QTest.keyClick(recorder, key)
    assert recorder.text() == ""


def test_a_held_key_is_recorded_once(recorder):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    changes = []
    recorder.keysChanged.connect(changes.append)
    for repeat in (False, True, True):
        QApplication.sendEvent(recorder, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, CTRL_ALT, "", repeat))
    assert changes == ["Ctrl+Alt+Up"]


def test_recording_lets_go_of_the_shortcuts_and_closing_takes_them_back():
    from datetime import UTC, datetime

    from nightlight.color.controller import NightLightController
    from nightlight.ui.settings_window import SettingsWindow
    from tests.test_settings_window import FakeGamma

    paused = []
    controller = NightLightController(FakeGamma(), AppConfig().night_light, lambda: datetime(2026, 6, 15, 12, tzinfo=UTC))
    window = SettingsWindow(controller, AppConfig(shortcuts=(UP,)), pause_shortcuts=paused.append)
    active(window)
    window.show_page(3)
    field = window.shortcut_editor.rows[0].keys
    field.setFocus()
    assert paused == [True]
    window.setFocus()  # elsewhere in the window
    assert paused == [True, False]
    field.setFocus()
    window.close()  # closed while recording
    assert paused[-1] is False
    controller.shutdown()


# --- The editor ----------------------------------------------------------------------------------


def test_rows_become_shortcuts_with_only_what_their_action_uses():
    from nightlight.ui.shortcut_editor import ShortcutEditor

    editor = ShortcutEditor()
    editor.set_displays([("DEL41A2", "DELL U2720Q")])
    editor.set_shortcuts((Shortcut("Ctrl+Alt+N", SUSPEND), Shortcut("F13", BRIGHTNESS_SET, 40, "DEL41A2"),
                          Shortcut("F14", BRIGHTNESS_UP, 5, "GONE")))
    toggle, level, gone = editor.rows
    assert toggle.value.isHidden() and toggle.display.isHidden() and not level.value.isHidden()
    assert gone.display.currentText() == "GONE (not connected)"  # kept, though not connected
    assert editor.shortcuts() == (Shortcut("Ctrl+Alt+N", SUSPEND, 10), Shortcut("F13", BRIGHTNESS_SET, 40, "DEL41A2"),
                                  Shortcut("F14", BRIGHTNESS_UP, 5, "GONE"))
    level.action.setCurrentIndex(level.action.findData(NIGHT_LIGHT))  # a switch: no amount, every display
    assert editor.shortcuts()[1] == Shortcut("F13", NIGHT_LIGHT, 10, "")


def test_a_new_row_without_keys_isnt_a_shortcut_yet_and_says_how():
    from nightlight.ui.shortcut_editor import NO_KEYS, ShortcutEditor

    editor = ShortcutEditor()
    recording = []
    editor.recordingChanged.connect(recording.append)
    active(editor)
    editor.add_button.click()
    assert editor.shortcuts() == () and recording == [True]  # the new field is recording
    editor.show_status(lambda keys: "", ())
    assert editor.rows[0].status.text() == NO_KEYS
    editor.rows[0].remove.click()  # removed while recording: shortcuts come back
    assert editor.rows == [] and recording[-1] is False
    editor.hide()


def test_no_more_than_32_rows():
    from nightlight.ui.shortcut_editor import MAX_ROWS, ShortcutEditor

    editor = ShortcutEditor()
    for _ in range(MAX_ROWS + 3):
        editor._add(Shortcut())
    assert len(editor.rows) == MAX_ROWS and not editor.add_button.isEnabled()


# --- The overlay ---------------------------------------------------------------------------------


def render(widget, width=300, height=200):
    widget.resize(width, height)
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    widget.render(image)  # raises on an error in paintEvent
    return image


@pytest.mark.parametrize("dark", [False, True])
def test_the_overlay_paints_levels_and_messages(dark):
    from nightlight.ui.shortcut_overlay import MAX_ROWS, ShortcutOverlay

    overlay = ShortcutOverlay()
    if dark:
        palette = overlay.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        overlay.setPalette(palette)
    overlay.show_levels([("A display with a very long name that won't fit in the overlay at all", 150), ("TV", -5)] * 5)
    assert len(overlay._levels) == MAX_ROWS
    render(overlay, overlay.width(), overlay.height())
    overlay.show_message("Night light: Suspended until manually resumed, a message too long for one line")
    render(overlay, overlay.width(), overlay.height())
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    overlay.hide()


def test_the_overlay_goes_by_itself_and_each_use_keeps_it_up(monkeypatch):
    from nightlight.ui import shortcut_overlay

    monkeypatch.setattr(shortcut_overlay, "SHOW_MS", 50)
    overlay = shortcut_overlay.ShortcutOverlay()
    overlay._timer.setInterval(50)
    overlay.show_message("Night light: On")
    QTest.qWait(30)
    overlay.show_message("Night light: Off")  # again before it went
    QTest.qWait(30)
    assert overlay.isVisible()
    QTest.qWait(60)
    assert not overlay.isVisible()


# --- On Windows, for real ---------------------------------------------------------------------------

REAL = """
import sys, ctypes
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from nightlight.hardware import winsystem
from nightlight.core.shortcuts import parse
events = winsystem.SystemEvents(app)
seen = []
events.hotkeyPressed.connect(seen.append)
mods, vk = parse("Ctrl+Alt+Shift+F24").codes
first, second = events.register_hotkey(41, mods, vk), events.register_hotkey(42, mods, vk)
ctypes.windll.user32.PostMessageW(ctypes.c_void_p(events._hwnd), winsystem.WM_HOTKEY, 41, 0)
def finish():
    events.unregister_hotkey(41)
    again = events.register_hotkey(43, mods, vk)
    events.unregister_hotkey(43)
    print(first, second, seen, again)
    app.quit()
QTimer.singleShot(300, finish)
app.exec()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")
def test_registering_with_windows_and_hearing_the_shortcut():
    """On Windows' own platform (not the tests' offscreen one): registered,
    refused the second time (1409), heard through the native event filter,
    and free again once let go."""
    env = {**os.environ, "QT_QPA_PLATFORM": "windows"}
    result = subprocess.run([sys.executable, "-c", REAL, str(ROOT)], capture_output=True, text=True, timeout=60, env=env)
    assert result.stdout.split("\n")[-2] == "0 1409 [41] 0", result.stderr[-2000:]


def test_only_the_first_of_two_rows_with_the_same_keys_is_said_to_work():
    from nightlight.system.shortcuts import DUPLICATE
    from nightlight.ui.shortcut_editor import ShortcutEditor

    editor = ShortcutEditor()
    saved = (UP, Shortcut("Ctrl+Alt+Up", BRIGHTNESS_SET, 50))
    editor.set_shortcuts(saved)
    editor.show_status({"Ctrl+Alt+Up": WORKS}.get, saved)
    assert [row.status.text() for row in editor.rows] == [WORKS, DUPLICATE]
