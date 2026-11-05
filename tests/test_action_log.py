# SPDX-License-Identifier: GPL-3.0-only
"""What the user did shows in the log, and where it was done from. A
tester's report (0.7.5) showed what Winlight did, but hardly what was tried:
settings, night light turned on or off, levels set by hand. Never a value
that could be personal (a city, app names, a display's own name)."""

import logging
from dataclasses import replace

from nightlight.brightness import monitors as monitors_module
from nightlight.brightness.monitors import SCHEDULE, MonitorManager
from nightlight.config import GeneralConfig
from nightlight.core.shortcuts import SUSPEND, Shortcut
from tests.test_app import start  # noqa: F401  (a fixture)
from tests.test_monitors import SlowBackend, ready, wait_until


def lines(caplog, logger: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger]


def test_each_way_of_changing_night_light_says_where_it_came_from(start, caplog):  # noqa: F811
    night_light, _ = start(GeneralConfig(start_minimized=True), night_light={"enabled": True, "mode": "always"})
    with caplog.at_level(logging.INFO, logger="nightlight.color.controller"):
        tray = night_light.tray
        tray._menu.aboutToShow.emit()
        tray._override_action.menu().actions()[-1].trigger()  # Suspend Night Light > Until manually resumed
        tray._menu.aboutToShow.emit()
        tray._override_action.trigger()  # Resume Night Light
        night_light._run_shortcut(Shortcut("Ctrl+Alt+F9", SUSPEND))
        night_light.handle_request({"command": "night-light", "action": "resume"}, lambda _reply: None)
        night_light.flyout._on_toggle_clicked()  # the panel's Suspend
        night_light.show_settings()
        night_light._settings.banner_button.click()  # Settings' Resume
    assert lines(caplog, "nightlight.color.controller") == [
        "Night light suspended until resumed, from the tray menu",
        "Night light back to its schedule, from the tray menu",
        "Night light suspended until resumed, from a shortcut",
        "Night light back to its schedule, from the command line",
        "Night light suspended until resumed, from the panel",
        "Night light back to its schedule, from Settings",
    ]
    night_light._settings.close()


def test_a_timed_override_says_until_when(start, caplog):  # noqa: F811
    night_light, _ = start(GeneralConfig(start_minimized=True), night_light={"enabled": True, "mode": "always"})
    tray = night_light.tray
    with caplog.at_level(logging.INFO, logger="nightlight.color.controller"):
        tray._menu.aboutToShow.emit()
        tray._override_action.menu().actions()[0].trigger()  # For 1 hour
    until = night_light.controller.override.until
    assert lines(caplog, "nightlight.color.controller") == [f"Night light suspended until {until:%Y-%m-%d %H:%M}, from the tray menu"]


def test_settings_applied_names_the_pages_and_settings_never_their_values(start, caplog):  # noqa: F811
    night_light, _ = start(GeneralConfig(start_minimized=True))
    old = night_light._config
    new = replace(old, night_light=replace(old.night_light, night_temperature=3123, exempt_apps=("secret-app.exe",)),
                  general=replace(old.general, theme="dark", keep_calibration=not old.general.keep_calibration))
    with caplog.at_level(logging.INFO, logger="nightlight.app"):
        night_light._apply_settings(new)
        night_light._apply_settings(new)  # the same again: nothing changed, nothing said
    applied = [line for line in lines(caplog, "nightlight.app") if line.startswith("Settings applied")]
    assert applied == [("Settings applied, from Settings: Night Light (night_temperature, exempt_apps), "
                        "Displays (keep_calibration), General (theme)")]
    assert "secret-app" not in applied[0] and "3123" not in applied[0]


def test_brightness_set_by_hand_is_logged_once_it_settles(monkeypatch, caplog):
    """A drag sends a level every 100 ms: the log gets the one it ends on,
    by the display's model name; the schedule's levels aren't the user's."""
    monkeypatch.setattr(monitors_module, "CHOSEN_LOG_SETTLE_MS", 60)
    monitors = MonitorManager(SlowBackend(delay=0))
    try:
        state = ready(monitors)
        with caplog.at_level(logging.INFO, logger="nightlight.brightness.monitors"):
            for level in (20, 35, 50, 65):  # a drag
                monitors.set_brightness("A", level)
            monitors.set_brightness("A", 30, source=SCHEDULE)  # not the user's
            assert wait_until(lambda: any("set by the user" in line for line in lines(caplog, "nightlight.brightness.monitors")))
            monitors.set_brightness("A", 80)  # just before quitting: logged at shutdown, not lost
            monitors.shutdown()
    finally:
        monitors.shutdown()
    chosen = [line for line in lines(caplog, "nightlight.brightness.monitors") if "set by the user" in line]
    assert chosen == [f"Brightness set by the user: {state.info.name} 65%", f"Brightness set by the user: {state.info.name} 80%"]
