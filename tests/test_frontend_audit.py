# SPDX-License-Identifier: GPL-3.0-only
"""The windows' promises to the people using them, checked on every control
rather than one example: a fixed rule here catches the control added next
year as well as today's.

- Every control has a name a screen reader can say (Narrator reads
  "combo box" and nothing else for one without).
- Switches show their focus ring for the keyboard only (Windows 11).
- Dialogs never start an event loop of their own (test_architecture.py
  checks the source; here, the dialogs the windows open).
"""

from datetime import UTC, datetime

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QScrollBar,
    QWidget,
)

from nightlight.color.controller import NightLightController
from nightlight.config import AppConfig, BrightnessScheduleConfig, NightLightConfig
from nightlight.core.brightness_schedule import PRESETS
from nightlight.ui.flyout import Flyout
from nightlight.ui.settings_parts import ToggleSwitch
from nightlight.ui.settings_window import SettingsWindow
from tests.test_flyout import FakeGamma, FakeMonitors

CONTROLS = (QAbstractButton, QComboBox, QAbstractSpinBox, QAbstractSlider, QLineEdit)
NOON = datetime(2026, 6, 15, 12, tzinfo=UTC)


def spoken_name(widget: QWidget) -> str:
    """What a screen reader says for it, as Qt tells it (its accessible
    name, a button's text, a label set as its buddy...)."""
    interface = QAccessible.queryAccessibleInterface(widget)
    return interface.text(QAccessible.Text.Name).strip() if interface is not None else ""


def unnamed(window: QWidget, skip=()) -> list[str]:
    found = []
    for widget in window.findChildren(QWidget):
        if not isinstance(widget, CONTROLS) or isinstance(widget, QScrollBar) or widget in skip:
            continue
        if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
            continue  # a spin box's or combo box's own text field: the box is named
        if not spoken_name(widget):
            found.append(f"{type(widget).__name__} in {type(widget.parentWidget()).__name__} (tooltip: {widget.toolTip()!r})")
    return found


@pytest.fixture
def settings():
    controller = NightLightController(FakeGamma(), NightLightConfig(), lambda: NOON)
    preset = PRESETS["follow_sun"]  # sun-tied times: every kind of schedule row
    config = AppConfig(NightLightConfig(), brightness_schedule=BrightnessScheduleConfig(True, "follow_sun", preset.points,
                                                                                         preset.transition_minutes))
    window = SettingsWindow(controller, config, True)
    yield window
    controller.shutdown()


def test_every_settings_control_has_a_name_a_screen_reader_can_say(settings):
    # The banner's button gets its text when the banner shows.
    assert unnamed(settings, skip=(settings.banner_button,)) == []


def test_a_settings_row_names_its_control_after_its_title_and_describes_it(settings):
    assert settings.mode.accessibleName() == "Schedule" and settings.mode.accessibleDescription() == "When night light is on"
    assert settings.night_temperature.slider.accessibleName() == "Night"  # the slider itself, not its frame


def test_every_panel_control_has_a_name_a_screen_reader_can_say():
    controller = NightLightController(FakeGamma(), NightLightConfig(), lambda: NOON)
    flyout = Flyout(FakeMonitors(), controller, as_window=True)
    try:
        assert unnamed(flyout) == []
        sliders = [spoken_name(slider) for slider in flyout.findChildren(QAbstractSlider)]
        assert "DELL brightness" in sliders and "Built-in display brightness" in sliders  # which display each one is
    finally:
        controller.shutdown()


def test_switches_show_their_focus_ring_for_the_keyboard_only(settings):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    settings.show()
    settings.activateWindow()
    QTest.qWaitForWindowActive(settings)
    switches = [switch for switch in settings.findChildren(ToggleSwitch) if switch.isVisible()]
    assert len(switches) >= 3
    for switch in switches:
        switch.setFocus(Qt.FocusReason.MouseFocusReason)
        assert not switch.shows_focus_ring(), switch.text()
        (switches[1] if switch is switches[0] else switches[0]).setFocus(Qt.FocusReason.MouseFocusReason)
        switch.setFocus(Qt.FocusReason.TabFocusReason)  # Tab, from the switch before
        assert switch.hasFocus() and switch.shows_focus_ring(), switch.text()
    settings.hide()


def test_the_settings_windows_dialogs_are_window_modal_never_app_modal(settings):
    from PySide6.QtCore import Qt

    settings.show()
    settings._restore_defaults()  # asks first
    dialogs = [d for d in settings.findChildren(QDialog) if d.isVisible()]
    assert dialogs and all(d.windowModality() == Qt.WindowModality.WindowModal for d in dialogs)
    for dialog in dialogs:
        dialog.reject()
