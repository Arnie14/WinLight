# SPDX-License-Identifier: GPL-3.0-only
"""Small improvements from the GUI audit before 0.8.0 Beta 1: kelvin
written one way, time fields that go round the clock, offsets from the
sun that say which way, rows that line up, notes next to what they are
about, a link that looks like one, the HDR setting only where it applies,
and details that show while their switch is on."""

import ctypes

import pytest
from PySide6.QtCore import QTime
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QTimeEdit

from nightlight.config import Anchor, DisplayPrefs, GeneralConfig, NightLightConfig, SchedulePoint
from nightlight.hardware import win32
from nightlight.hardware.brightness import DisplayDetails, FakeBrightnessBackend, MonitorInfo
from nightlight.ui.schedule_editor import PointRow, parse_offset
from nightlight.ui.settings_parts import ActionButton, contrast, link_color
from nightlight.ui.settings_widgets import AppList, DisplayList, hdr_setting_applies
from tests.test_settings_window import make_window


@pytest.fixture
def window():
    window, controller = make_window(NightLightConfig(enabled=True), GeneralConfig())
    yield window
    controller.shutdown()


# --- 1. Kelvin, with a space -------------------------------------------------------------


def test_the_status_writes_kelvin_with_a_space_as_everywhere_else(window):
    from nightlight.ui.night_light_text import night_light_status

    assert night_light_status(window._controller).endswith(" K")


# --- 2. Time fields go round the clock ----------------------------------------------------


def test_every_time_field_goes_round_the_clock(window):
    """A bedtime of 00:30: the up arrow stopped at 23:00 and it had to be typed."""
    fields = window.findChildren(QTimeEdit)
    assert len(fields) >= 5 and all(field.wrapping() for field in fields)
    window.bedtime.setTime(QTime(23, 30))
    window.bedtime.setCurrentSection(QTimeEdit.Section.HourSection)
    window.bedtime.stepBy(1)
    assert window.bedtime.time() == QTime(0, 30)


def test_a_bedtime_after_midnight_starts_night_light_the_evening_before(window):
    window.bedtime.setTime(QTime(0, 30))
    window.use_sleep_schedule.click()
    assert window.night_start.time() == QTime(21, 30)


# --- 3 and 4. Offsets from the sun, and rows that line up --------------------------------------


@pytest.mark.parametrize(("text", "minutes"), [
    ("30 min after", 30), ("15 min before", -15), ("45", 45), ("-15", -15), ("−15 min", -15), ("0 min", 0),
    ("90 MIN BEFORE", -90), ("", None), ("min", None), ("soon", None),
])
def test_an_offset_is_read_from_words_or_a_signed_number(text, minutes):
    assert parse_offset(text) == minutes


def test_an_offset_says_which_way_and_rows_by_clock_and_sun_line_up():
    row = PointRow(SchedulePoint(80, anchor=Anchor.SUNRISE, offset_minutes=30))
    assert row.offset.text() == "30 min after"
    row.offset.setValue(-15)
    assert row.offset.text() == "15 min before" and row.point().offset_minutes == -15
    assert row.offset.width() == row.time.width()  # a row by the clock and one by the sun line up
    longest = row.offset.textFromValue(row.offset.minimum())
    assert row.offset.fontMetrics().horizontalAdvance(longest) < row.offset.width()


def test_an_offset_can_be_typed():
    row = PointRow(SchedulePoint(80, anchor=Anchor.SUNSET, offset_minutes=0))
    row.offset.lineEdit().selectAll()
    row.offset.lineEdit().insert("45 min before")
    row.offset.interpretText()
    assert row.offset.value() == -45
    assert row.offset.buttonSymbols() != QAbstractSpinBox.ButtonSymbols.NoButtons


# --- 5. The note about Fn keys sits under the shortcuts ------------------------------------------


def test_the_note_about_fn_keys_is_under_the_shortcuts_it_is_about(window):
    layout = window.keys_hint.parentWidget().layout()
    assert layout.indexOf(window.keys_hint) == layout.indexOf(window.shortcut_editor) + 1


# --- 6. A link looks like one --------------------------------------------------------------------


def test_the_switching_guide_is_drawn_as_a_link(window):
    from nightlight.config import AppConfig
    from nightlight.ui.welcome import WelcomeWindow

    welcome = WelcomeWindow(window._controller, AppConfig)
    assert welcome.guide.kind == "link"
    assert ActionButton("x", "link").sizeHint().width() < ActionButton("x", "standard").sizeHint().width()
    welcome.deleteLater()


@pytest.mark.parametrize(("window_color", "text_color", "accent"), [
    ("#f3f3f3", "#1a1a1a", "#0067c0"),  # Windows' blue on light
    ("#f3f3f3", "#1a1a1a", "#ffd60a"),  # a pale accent on light
    ("#202020", "#f0f0f0", "#4cc2ff"),  # Windows' blue on dark
    ("#202020", "#f0f0f0", "#003e92"),  # a deep accent on dark
])
def test_link_text_is_readable_whatever_the_accent(window_color, text_color, accent):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window_color))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text_color))
    palette.setColor(getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight), QColor(accent))
    assert contrast(link_color(palette), QColor(window_color)) >= 4.5


# --- 7. The HDR setting only where it applies ---------------------------------------------------


def display(key, channel, hdr=False, capable=False):
    return MonitorInfo(0, key, True, key=key, channel=channel, hdr=hdr,
                       details=DisplayDetails(key[:3], key, hdr=hdr, hdr_capable=capable))


DDC_HDR = display("DEL41A2", "ddc", capable=True)
DDC_PLAIN = display("ACR0001", "ddc")
SOFTWARE_TV = display("SAM7136", "software", capable=True)
PANEL = display("AUO24ED", "wmi", capable=True)
SDR_HDR = display("GSM5BBF", "sdr", hdr=True, capable=True)


@pytest.mark.parametrize(("monitor", "applies"), [
    (DDC_HDR, True), (display("DEL41A2", "ddc-high-level", hdr=True), True), (DDC_PLAIN, False),
    (SOFTWARE_TV, False), (PANEL, False), (SDR_HDR, False), (None, False),
])
def test_the_hdr_setting_applies_to_ddc_ci_displays_that_can_show_hdr(monitor, applies):
    assert hdr_setting_applies(monitor) is applies


def boxes(displays: DisplayList):
    return {key: not hdr.isHidden() for key, (_name, _show, hdr) in displays._rows.items()}


def test_the_hdr_box_shows_only_where_it_applies_or_is_already_on():
    displays = DisplayList()
    displays.set_displays([DDC_HDR, DDC_PLAIN, SOFTWARE_TV], (DisplayPrefs("SAM7136", hdr_manual=True),))
    assert boxes(displays) == {"DEL41A2": True, "ACR0001": False, "SAM7136": True}  # the TV's is on: it can be turned off
    assert not displays._hdr_note.isHidden()
    displays.set_displays([DDC_PLAIN, SOFTWARE_TV], ())
    assert boxes(displays) == {"ACR0001": False, "SAM7136": False}
    assert displays._hdr_note.isHidden()  # nothing to explain
    assert QApplication.topLevelWidgets().count(displays) == 1  # no box opened as a window of its own
    displays.deleteLater()


def test_the_demo_displays_show_it_on_the_dell_alone():
    monitors = FakeBrightnessBackend(latency=0).list_monitors()
    assert [m.name for m in monitors if hdr_setting_applies(m)] == ["DELL U2720Q"]


class _FakeDeviceInfo:
    """DisplayConfigGetDeviceInfo, answering the HDR queries with set bits."""

    def __init__(self, new=None, old=None):
        self.new, self.old = new, old

    def __call__(self, header):
        if header.type == win32.DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2:
            if self.new is None:
                return win32.ERROR_NOT_SUPPORTED
            info = ctypes.cast(ctypes.addressof(header), ctypes.POINTER(win32.DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2)).contents
            info.value, info.activeColorMode = self.new
            return win32.ERROR_SUCCESS
        info = ctypes.cast(ctypes.addressof(header), ctypes.POINTER(win32.DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO)).contents
        info.value = self.old
        return win32.ERROR_SUCCESS


@pytest.mark.parametrize(("new", "old", "state"), [
    ((0x10 | 0x1, 1), None, (False, True)),  # 24H2: HDR supported, SDR mode now
    ((0x1, 1), None, (False, False)),  # 24H2: advanced color (wide color, auto color management), no HDR
    ((0x10 | 0x3, win32.DISPLAYCONFIG_ADVANCED_COLOR_MODE_HDR), None, (True, True)),  # in HDR now
    (None, 0x1, (False, True)),  # before 24H2: advanced color supported, off
    (None, 0x3, (True, True)),  # before 24H2: on
    (None, 0x0, (False, False)),
])
def test_windows_says_whether_a_display_can_show_hdr(monkeypatch, new, old, state):
    monkeypatch.setattr(win32, "_device_info", _FakeDeviceInfo(new, old))
    monkeypatch.setattr(win32, "_advanced_color_2", None)
    assert win32._hdr_state(win32.LUID(0, 0), 0) == state


# --- 8. Details show while their switch is on ---------------------------------------------------


def test_idle_dimming_details_show_only_while_it_is_on(window):
    window.show()
    window.show_page(1)
    assert not window.idle_dim.isChecked()
    assert all(row.isHidden() for row in window._idle_rows)  # no empty, greyed-out list taking room
    window.idle_dim.setChecked(True)
    assert not any(row.isHidden() for row in window._idle_rows)
    window.idle_dim.setChecked(False)
    assert all(row.isHidden() for row in window._idle_rows)
    window.close()


def test_pausing_details_show_only_while_their_switch_is_on(window):
    window.pause_for_apps.setChecked(False)
    window.never_pause.setChecked(False)
    assert window.exempt_apps.isHidden() and window._never_pause_when.isHidden()
    window.pause_for_apps.setChecked(True)
    window.never_pause.setChecked(True)
    assert not window.exempt_apps.isHidden() and not window._never_pause_when.isHidden()


def test_secondary_text_follows_a_theme_switched_in_settings():
    """Switching the theme (Qt's colour scheme override) reaches labels as
    PaletteChange only: the header's tagline, page subtitles and every
    description kept the old mode's grey until a restart."""
    from PySide6.QtCore import QEvent

    from nightlight.ui.widgets import SecondaryLabel

    app = QApplication.instance()
    light = app.palette()
    label = SecondaryLabel("Brightness and night light for every display")
    light_grey = label.palette().color(QPalette.ColorRole.WindowText)
    dark = QPalette(light)
    dark.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    events = []
    try:
        app.setPalette(dark)
        label.setPalette(QPalette(label.palette()))  # as if the application-wide event had been missed
        stale = label.palette()
        stale.setColor(QPalette.ColorRole.WindowText, light_grey)
        label.setPalette(stale)
        original = label.changeEvent
        label.changeEvent = lambda event: (events.append(event.type()), original(event))
        QApplication.sendEvent(label, QEvent(QEvent.Type.PaletteChange))
        assert label.palette().color(QPalette.ColorRole.WindowText).lightnessF() > 0.5  # light grey on dark now
        assert len(events) < 5  # recolouring didn't set off more palette changes for ever
    finally:
        app.setPalette(light)
        label.deleteLater()


def test_brightness_today_is_a_chart_with_the_level_now():
    from datetime import UTC, datetime, timedelta

    from PySide6.QtGui import QImage

    from nightlight.ui.day_ribbon import BrightnessDay

    noon = datetime(2026, 6, 15, 12, tzinfo=UTC)
    chart = BrightnessDay(lambda moment: 80 if 7 <= moment.hour < 21 else 30, lambda: noon)
    assert chart.level_now() == 80
    chart.set_marker(noon + timedelta(hours=10))  # 22:00, as the 24-hour preview would
    assert chart.level_now() == 30
    assert "the line is the level" in chart.toolTip()
    for width in (3, 40, 600):  # paints at any width, without raising
        chart.resize(width, chart.height())
        image = QImage(chart.size(), QImage.Format.Format_ARGB32)
        chart.render(image)
    chart.deleteLater()


def prompt():
    from nightlight.ui.prompt import Prompt

    box = Prompt(None, "Winlight: Restore defaults", "Put the default settings back?", "Nothing is saved until Apply.")
    main = box.add_button("Restore defaults", "accent", default=True)
    cancel = box.add_button("Cancel")
    return box, main, cancel


def test_a_prompt_answers_with_the_button_chosen():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    box, main, cancel = prompt()
    box.open()
    QTest.keyClick(box, Qt.Key.Key_Return)  # Enter: the main action
    assert box.clicked is main and not box.isVisible()
    box, main, cancel = prompt()
    box.open()
    cancel.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(box, Qt.Key.Key_Return)  # Enter on the focused button chooses it
    assert box.clicked is cancel
    box, main, cancel = prompt()
    box.open()
    QTest.keyClick(box, Qt.Key.Key_Escape)  # Esc: no answer, as Cancel
    assert box.clicked is None and not box.isVisible()


def test_a_prompt_lays_out_as_windows_11_does():
    box, main, cancel = prompt()
    layout = box._footer_layout
    assert [layout.itemAt(i).widget() for i in range(layout.count())] == [main, cancel]  # main first, Cancel last
    assert main.kind == "accent" and cancel.kind == "standard"
    box.open()
    QApplication.processEvents()
    assert main.width() == cancel.width()  # equally wide, across the footer
    assert box.accessibleName() == "Put the default settings back?"
    box.reject()


def test_closing_settings_with_changes_and_pressing_esc_keeps_editing(window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    monkeypatch.setattr(window, "_is_users_close", lambda event: True)
    window.show()
    window.night_temperature.setValue(3000)
    window.close()
    QTest.keyClick(window._close_box, Qt.Key.Key_Escape)
    assert window.isVisible() and window.night_temperature.value() == 3000 and window._close_box is None
    window.close()
    window._close_discard.click()


def test_an_app_list_is_as_tall_as_its_apps():
    apps = AppList(list, installed=list)
    assert not apps.empty.isHidden() and apps.list.isHidden() and apps._remove.isHidden()
    apps.set_apps(("a.exe",))
    one = apps.list.height()
    assert apps.empty.isHidden() and not apps.list.isHidden() and not apps._remove.isHidden()
    apps.set_apps(("a.exe", "b.exe", "c.exe"))
    three = apps.list.height()
    assert three > one
    apps.set_apps(tuple(f"{n}.exe" for n in range(12)))
    assert apps.list.height() == apps.list.sizeHintForRow(0) * AppList.MAX_ROWS + 2 * apps.list.frameWidth() + 4  # then it scrolls
    apps.set_apps(("a.exe",))
    apps.list.setCurrentRow(0)
    apps._remove_selected()  # the last one removed: the "none yet" line again
    assert not apps.empty.isHidden() and apps.list.isHidden() and apps._remove.isHidden()
    apps.deleteLater()
