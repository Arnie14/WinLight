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
from nightlight.ui.welcome import WelcomeWindow, findings, when_text

NOON = datetime(2026, 11, 4, 12, tzinfo=UTC)
PANEL = MonitorInfo(0, "Built-in display", True, key="AUO24ED", internal=True, channel="wmi")
DELL = MonitorInfo(1, "DELL U2720Q", True, key="DEL41A2", channel="ddc")
TV = MonitorInfo(2, "SAMSUNG", True, key="SAM7136", channel="software", control="software")
OLD = MonitorInfo(3, "Old monitor", False, key="ACI0001", reason="DDC/CI didn't answer")


class FakeGamma:
    def apply(self, kelvin):
        pass

    def reset(self):
        pass


def names(found):
    return [f.title for f in found]


def test_nothing_found_on_a_pc_where_nothing_clashes():
    assert findings(False, {"explorer.exe", "winlight.exe"}, [PANEL, DELL], lambda m: m.name) == []


def test_windows_night_light_on_comes_first_with_a_way_to_turn_it_off():
    [found] = findings(True, set(), [], lambda m: m.name)
    assert found.title == "Windows Night Light is on" and found.url == "ms-settings:nightlight" and found.action


def test_other_tools_running_are_named_with_what_to_do():
    found = findings(None, {"flux.exe", "twinkle tray.exe", "monitorian.exe", "lightbulb.exe", "notepad.exe"}, [], lambda m: m.name)
    assert names(found) == ["f.lux is running", "LightBulb is running", "Twinkle Tray is running", "Monitorian is running"]
    assert all(f.description for f in found)


def test_external_displays_without_ddc_ci_are_named_by_the_users_name_for_them():
    found = findings(None, set(), [PANEL, DELL, TV, OLD], lambda m: {"SAM7136": "Living room TV"}.get(m.key, m.name))
    assert names(found) == ["Living room TV doesn't answer DDC/CI", "Old monitor doesn't answer DDC/CI"]
    assert "dimmed through its colors" in found[0].description and "dimmed" not in found[1].description


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
        assert window.found == ["f.lux is running"]
        window.set_windows_night_light(True)
        assert window.found == ["Windows Night Light is on", "f.lux is running"]
        programs.clear()
        monitors.monitors = [PANEL, TV]
        monitors.monitorsChanged.emit(monitors.monitors)  # detection found the TV
        assert window.found == ["Windows Night Light is on", "TV doesn't answer DDC/CI"]
        window.set_windows_night_light(False)
        monitors.monitors = [PANEL]
        monitors.monitorsChanged.emit(monitors.monitors)
        assert window.found == ["Nothing here clashes with Winlight"]
        window.show()
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
