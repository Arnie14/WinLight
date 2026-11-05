# SPDX-License-Identifier: GPL-3.0-only
"""The welcome screen (ui/welcome.py): what it finds on this PC, and when
the app shows it."""

import dataclasses
import json
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from nightlight import app as app_module
from nightlight.color.controller import NightLightController
from nightlight.config import AppConfig, DisplayPrefs, GeneralConfig, Mode, NightLightConfig
from nightlight.hardware import create_backends
from nightlight.hardware.brightness import MonitorInfo
from nightlight.ui.welcome import WelcomeWindow, display_lines, findings, tray_tip, when_text

NOON = datetime(2026, 11, 4, 12, tzinfo=UTC)
PANEL = MonitorInfo(0, "Built-in display", True, key="AUO24ED", internal=True, channel="wmi")
DELL = MonitorInfo(1, "DELL U2720Q", True, key="DEL41A2", channel="ddc")
TV = MonitorInfo(2, "SAMSUNG", True, key="SAM7136", channel="software", control="software")
OLD = MonitorInfo(3, "Old monitor", False, key="ACI0001", reason="DDC/CI didn't answer")
HDR = MonitorInfo(4, "LG ULTRAGEAR", True, key="GSM5BBF", channel="sdr", control="sdr", hdr=True)


class FakeGamma:
    def apply(self, kelvin):
        pass

    def reset(self):
        pass


def names(found):
    return [f.title for f in found]


def test_nothing_found_on_a_pc_where_nothing_clashes():
    assert findings(False, {"explorer.exe", "winlight.exe"}) == []


def test_windows_night_light_on_comes_first_with_a_way_to_turn_it_off():
    [found] = findings(True, set())
    assert found.title == "Windows Night Light is on" and found.url == "ms-settings:nightlight" and found.action


def test_other_tools_running_are_named_with_what_to_do():
    found = findings(None, {"flux.exe", "twinkle tray.exe", "monitorian.exe", "lightbulb.exe", "notepad.exe"})
    assert names(found) == ["f.lux is running", "LightBulb is running", "Twinkle Tray is running", "Monitorian is running"]
    assert all(f.description for f in found)


def test_the_other_tools_the_installer_notes_name_are_found_too():
    """The installer's notes list these as clashing; the welcome screen found
    only four. ClickMonitorDDC's program carries its version in its name."""
    found = findings(None, {"iris.exe", "careueyes.exe", "clickmonitorddc_7_2.exe", "ddpm.exe", "onscreen control.exe"})
    assert names(found) == ["Iris is running", "CareUEyes is running", "ClickMonitorDDC is running",
                            "Dell Display Manager is running", "LG OnScreen Control is running"]
    assert names(findings(None, {"ddm.exe", "ddpm.exe"})) == ["Dell Display Manager is running"]  # one tool, named once
    assert findings(None, {"clickmonitorddc.txt", "irisx.exe", "my iris.exe"}) == []


def test_every_display_is_listed_with_how_it_is_controlled():
    lines = display_lines([PANEL, DELL, TV, OLD, HDR], lambda m: {"SAM7136": "Living room TV"}.get(m.key, m.name))
    assert names(lines) == ["Built-in display", "DELL U2720Q", "Living room TV", "Old monitor", "LG ULTRAGEAR"]
    panel, dell, tv, old, hdr = (line.description for line in lines)
    assert panel.startswith("Laptop brightness") and dell.startswith("DDC/CI")
    assert "dimmed through its colors" in tv and "Turn on DDC/CI" in tv
    assert "no brightness control" in old and "Turn on DDC/CI" in old
    assert "SDR content" in hdr and "can't tint it until HDR is off" in hdr  # Windows applies no gamma ramp in HDR
    assert hdr.count("HDR is on") == 1 and not any("HDR is on" in text for text in (panel, dell, tv, old))
    assert panel == ("Laptop brightness: the built-in display's backlight, as the laptop's brightness keys and Windows' "
                     "slider set it.")  # the panel's caption and its tooltip, as one sentence


def test_the_tray_icon_tip_only_when_windows_hides_the_icon():
    assert tray_tip(None) is None and tray_tip(False) is None  # can't tell, or on the taskbar: nothing to say
    tip = tray_tip(True)
    assert "under ^" in tip.title and tip.url == "ms-settings:taskbar" and tip.action


@pytest.mark.parametrize(("night_light", "says"), [
    (NightLightConfig(enabled=False), "Night light is off"),
    (NightLightConfig(enabled=True, mode=Mode.ALWAYS), "on all the time"),
    (NightLightConfig(enabled=True, mode=Mode.TIMES, night_start="21:00", day_start="07:00"), "21:00"),
])
def test_it_says_when_night_light_comes_on(night_light, says):
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    try:
        assert says in when_text(AppConfig(night_light), controller)
    finally:
        controller.shutdown()


class Monitors(QObject):
    monitorsChanged = Signal(list)

    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors


def test_the_window_shows_its_findings_and_looks_again_when_things_change():
    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    monitors = Monitors([PANEL])
    programs = {"flux.exe"}
    opened = []
    window = WelcomeWindow(controller, lambda: AppConfig(night_light, displays=(DisplayPrefs("SAM7136", "TV"),)), monitors,
                           programs=lambda: set(programs), open_settings=lambda: opened.append(True))
    try:
        window.show()  # it looks again only while shown (see the next test)
        assert window.found == ["f.lux is running"]
        assert [name for name, _how in window.displays] == ["Built-in display"]
        window.set_windows_night_light(True)
        assert window.found == ["Windows Night Light is on", "f.lux is running"]
        programs.clear()
        monitors.monitors = [PANEL, TV]
        monitors.monitorsChanged.emit(monitors.monitors)  # detection found the TV
        assert window.found == ["Windows Night Light is on"]
        assert [name for name, _how in window.displays] == ["Built-in display", "TV"]  # the user's name for it
        assert "Turn on DDC/CI" in window.displays[1][1]
        window.set_windows_night_light(False)
        monitors.monitors = [PANEL]
        monitors.monitorsChanged.emit(monitors.monitors)
        assert window.found == ["Nothing here clashes with Winlight"]
        window.settings.click()
        assert opened == [True] and not window.isVisible()
    finally:
        window.close()
        controller.shutdown()


# --- When the app shows it ---------------------------------------------------------------


@pytest.fixture
def start(tmp_path, monkeypatch):
    """Start the app; `fresh` leaves no settings file, as at the first start."""
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(app_module.winsystem, "running_programs", set)
    busy = {"now": False}
    monkeypatch.setattr(app_module.winsystem, "user_busy", lambda: busy["now"])
    started = []

    def run(fresh=True, general=GeneralConfig()):
        path = tmp_path / "settings.json"
        if not fresh:
            path.write_text(json.dumps({"general": dataclasses.asdict(general)}))
        night_light = app_module.NightLightApp(QApplication.instance(), *create_backends("fake"), path)
        started.append(night_light)
        return night_light

    yield run, busy
    for night_light in started:
        if night_light._welcome is not None:
            night_light._welcome.close()
        if night_light._settings is not None:
            night_light._settings.close()
        night_light.tray.hide()
        night_light._shutdown()


def test_the_first_start_shows_it_once(start):
    run, _busy = start
    first = run(fresh=True)
    assert first._welcome is not None and first._welcome.isVisible()
    first._welcome.close()
    first._shutdown()
    again = run(fresh=True)  # still no settings file: none was saved
    assert again._welcome is None


def test_an_upgrade_doesnt_show_it(start):
    run, _busy = start
    assert run(fresh=False)._welcome is None  # settings from an earlier version


def test_with_a_fullscreen_app_in_front_it_waits_for_the_next_start(start):
    run, busy = start
    busy["now"] = True
    first = run(fresh=True)
    assert first._welcome is None
    first._shutdown()
    busy["now"] = False
    later = run(fresh=False)  # the settings file may exist by now
    assert later._welcome is not None and later._welcome.isVisible()


def test_settings_shows_it_again(start):
    run, _busy = start
    night_light = run(fresh=False, general=GeneralConfig(start_minimized=True))
    night_light.show_settings()
    night_light._settings.show_welcome.click()
    assert night_light._welcome is not None and night_light._welcome.isVisible()


def test_looking_again_while_shown_leaves_room_for_everything():
    """Found in the real app: detection finishing while the window was open
    rebuilt the card, but a widget added to a shown window is shown later, so
    the height was worked out without it: an empty card, the title cut off."""
    from nightlight.ui.welcome import WIDTH

    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    monitors = Monitors([PANEL])
    window = WelcomeWindow(controller, lambda: AppConfig(night_light), monitors, programs=lambda: {"flux.exe"})
    try:
        window.show()
        QApplication.processEvents()
        monitors.monitors = [PANEL, TV, OLD]
        monitors.monitorsChanged.emit(monitors.monitors)  # detection finishes while it is open
        QApplication.processEvents()
        assert window.card.isVisible()
        assert window.height() >= window.layout().totalHeightForWidth(WIDTH)  # room for all of it
    finally:
        window.close()
        controller.shutdown()


def test_a_closed_welcome_screen_doesnt_look_at_anything():
    """The app keeps it after it's closed; each detection (waking, a display
    plugged in) rebuilt it and listed every program while nobody saw it."""
    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    monitors = Monitors([PANEL])
    looked = []
    window = WelcomeWindow(controller, lambda: AppConfig(night_light), monitors, programs=lambda: looked.append(1) or set())
    try:
        looked.clear()
        monitors.monitorsChanged.emit([PANEL])  # closed (never shown)
        window.set_windows_night_light(True)
        assert looked == []
        window.show()
        window.refresh()  # shown again: it looks then
        assert looked and window.found == ["Windows Night Light is on"]
    finally:
        window.close()
        controller.shutdown()


def test_the_tray_tip_shows_when_the_icon_is_hidden_and_looks_again_if_it_cant_tell_yet():
    """Explorer records a new tray icon a moment after it appears: at the
    first start the welcome screen can look before it has."""
    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    hidden = {"now": None}
    window = WelcomeWindow(controller, lambda: AppConfig(night_light), Monitors([PANEL]), tray_hidden=lambda: hidden["now"])
    try:
        window.show()
        window.refresh()
        assert window.found == ["Nothing here clashes with Winlight"] and window._tray_recheck.isActive()
        hidden["now"] = True  # recorded now, under ^
        window._tray_recheck.timeout.emit()
        assert window.found == ["Nothing here clashes with Winlight", "Winlight's icon is under ^ next to the clock"]
        hidden["now"] = False  # the user turned it on under Other system tray icons
        window.refresh()
        assert window.found == ["Nothing here clashes with Winlight"]
    finally:
        window.close()
        controller.shutdown()


def test_starting_at_sign_in_is_offered_where_it_is_off_and_stays_while_turned_on():
    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    state, turned = {"on": False}, []

    def turn(on):
        turned.append(on)
        state["on"] = on

    window = WelcomeWindow(controller, lambda: AppConfig(night_light), Monitors([PANEL]),
                           starts_at_sign_in=lambda: state["on"], start_at_sign_in=turn)
    already = WelcomeWindow(controller, lambda: AppConfig(night_light), Monitors([PANEL]),
                            starts_at_sign_in=lambda: True, start_at_sign_in=turn)
    try:
        window.show()
        window.refresh()
        assert "Start Winlight when I sign in" in window.found and not window.sign_in.isChecked()
        window.sign_in.click()
        assert turned == [True]
        window.refresh()  # on now, and still there: a switch mustn't vanish under the pointer
        assert "Start Winlight when I sign in" in window.found and window.sign_in.isChecked() and window.sign_in.isVisible()
        already.show()
        already.refresh()
        assert "Start Winlight when I sign in" not in already.found  # the installer's task: nothing to offer
    finally:
        window.close()
        already.close()
        controller.shutdown()


def test_the_welcome_screens_sign_in_switch_starts_winlight_at_sign_in_as_settings_does(start, monkeypatch):
    """The portable zip has no sign-in entry, though the saved setting can say
    on: the switch reads Windows first, then turns it on; and Settings, if
    open, takes the change, so its Apply doesn't put the old choice back."""
    from nightlight.config import AppConfig as Config

    class Entry:
        def __init__(self):
            self.enabled = False

        def is_enabled(self):
            return self.enabled

        def set_enabled(self, on):
            self.enabled = on

    run, _busy = start
    entry = Entry()
    monkeypatch.setattr(app_module.autostart, "create", lambda: entry)
    night_light = run(fresh=False, general=GeneralConfig(start_minimized=True, start_with_windows=True))
    night_light.show_settings()
    night_light.show_welcome()
    welcome = night_light._welcome
    assert "Start Winlight when I sign in" in welcome.found
    welcome.sign_in.click()
    assert entry.enabled and night_light._config.general.start_with_windows
    settings = night_light._settings
    assert settings._saved.general.start_with_windows and settings.start_with_windows.isChecked()
    assert isinstance(settings.current_config(), Config) and settings.current_config() == settings._saved  # nothing unsaved


def test_on_a_short_screen_the_cards_scroll_and_the_buttons_stay_in_view(monkeypatch):
    """Four displays and three tips need about 910 px; a 1366x768 laptop
    shows about 730: the window was taller than the screen, its buttons off it."""
    from nightlight.ui import welcome

    night_light = NightLightConfig(enabled=True, mode=Mode.ALWAYS)
    controller = NightLightController(FakeGamma(), night_light, lambda: NOON, start=False)
    monkeypatch.setattr(welcome.WelcomeWindow, "_screen_height", lambda self: 728)
    window = WelcomeWindow(controller, lambda: AppConfig(night_light), Monitors([PANEL, DELL, TV, OLD, HDR]),
                           programs=lambda: {"flux.exe", "iris.exe"}, tray_hidden=lambda: True,
                           starts_at_sign_in=lambda: False, start_at_sign_in=lambda on: None)
    tall = WelcomeWindow(controller, lambda: AppConfig(night_light), Monitors([PANEL, DELL, TV, OLD, HDR]),
                         programs=lambda: {"flux.exe", "iris.exe"}, tray_hidden=lambda: True)
    try:
        window.show()
        window.refresh()
        assert window.height() <= 728 - welcome.SCREEN_ALLOWANCE
        assert window.scroll.height() < window._cards.layout().totalHeightForWidth(welcome.WIDTH - 56)  # it scrolls
        assert window.done.isVisible() and window.done.geometry().bottom() < window.height()
        monkeypatch.setattr(welcome.WelcomeWindow, "_screen_height", lambda self: 2000)
        tall.show()
        tall.refresh()
        assert tall.scroll.height() == tall._cards.layout().totalHeightForWidth(welcome.WIDTH - 56)  # room: no scrolling
    finally:
        window.close()
        tall.close()
        controller.shutdown()
