# SPDX-License-Identifier: GPL-3.0-only
from datetime import UTC, datetime

import pytest

from nightlight.color.controller import NightLightController
from nightlight.config import BrightnessScheduleConfig, Mode, NightLightConfig
from nightlight.core.brightness_schedule import Boundary, ScheduledLevel
from nightlight.ui.tray import Tray


class FakeGamma:
    def apply(self, kelvin):
        pass

    def reset(self):
        pass


@pytest.fixture
def tray():
    controller = NightLightController(FakeGamma(), NightLightConfig(enabled=True, mode=Mode.ALWAYS), lambda: datetime(2026, 6, 15, 12, tzinfo=UTC))
    tray = Tray(controller)
    yield tray
    controller.shutdown()


def action(tray, text):
    return next(a for a in tray._menu.actions() if a.text() == text)


@pytest.mark.parametrize(("text", "signal"), [("Settings…", "configureRequested"), ("Quit", "quitRequested")])
def test_menu_items_work(tray, text, signal):
    # PySide6 6.8+ raises "signal instance is not callable" if a signal
    # itself is given to addAction, and the click then does nothing.
    received = []
    getattr(tray, signal).connect(lambda: received.append(True))
    action(tray, text).trigger()
    assert received == [True]


def test_tooltip_names_the_app_and_status(tray):
    assert tray.toolTip().splitlines() == ["Winlight", "Night Light: On · 4500 K"]


class FakeScheduler:
    def __init__(self, state, enabled=True):
        from PySide6.QtCore import QObject, Signal

        class Emitter(QObject):
            changed = Signal()

        self._emitter = Emitter()
        self.changed = self._emitter.changed
        self.state = state
        self.config = BrightnessScheduleConfig(enabled=enabled)


def level(now, target, nxt=None, end=None):
    since = Boundary(datetime(2026, 6, 15, 20, 0, tzinfo=UTC), target, 1)
    following = Boundary(datetime(2026, 6, 16, 7, 0, tzinfo=UTC), nxt, 0) if nxt is not None else None
    return ScheduledLevel(now, since, following, end is not None, False, end)


def test_tooltip_shows_the_brightness_schedule(tray):
    scheduler = FakeScheduler(level(70, 70, nxt=100))
    tray.set_scheduler(scheduler)
    assert "Brightness: 70% → 100% at 07:00" in tray.toolTip()
    scheduler.state = level(55, 40, nxt=100, end=datetime(2026, 6, 15, 20, 30, tzinfo=UTC))
    scheduler.changed.emit()
    assert "Brightness: 55% → 40%, changing until 20:30" in tray.toolTip()
    assert "·" not in tray.toolTip().split("Brightness:")[1]
    assert len(tray.toolTip()) < 128  # Windows cuts tray tooltips at 127 characters


def test_tooltip_leaves_out_a_schedule_that_is_off(tray):
    tray.set_scheduler(FakeScheduler(level(70, 70), enabled=False))
    assert "Brightness" not in tray.toolTip()
    tray.set_scheduler(FakeScheduler(None))
    assert "Brightness" not in tray.toolTip()


EVENING, NOON = datetime(2026, 6, 15, 21, 30, tzinfo=UTC), datetime(2026, 6, 15, 12, tzinfo=UTC)
SCHEDULED = NightLightConfig(enabled=True, mode=Mode.TIMES, night_start="20:00", day_start="07:00")


def menu_in(config, now, override=None):
    """The tray's menu as it opens: its visible items, and the tray."""
    from nightlight.core.schedule import OverrideKind

    controller = NightLightController(FakeGamma(), config, lambda: now)
    if override is not None:
        controller.set_override(OverrideKind[override], None)
    tray = Tray(controller)
    tray._menu.aboutToShow.emit()
    return [a for a in tray._menu.actions() if a.isVisible() and not a.isSeparator()], tray


@pytest.mark.parametrize(("config", "now", "override", "item", "choices"), [
    (SCHEDULED, EVENING, None, "Suspend Night Light", ["For 1 hour", "Until tomorrow evening", "Until manually resumed"]),
    (SCHEDULED, NOON, None, "Activate Night Light", ["For 1 hour", "Until tomorrow morning", "Until manually disabled"]),
    (SCHEDULED, EVENING, "SUSPEND", "Resume Night Light", []),
    (SCHEDULED, NOON, "ACTIVATE", "Turn Off Night Light", []),
    (NightLightConfig(), NOON, None, "Activate Night Light", ["For 1 hour", "Until tomorrow morning", "Until manually disabled"]),
])
def test_the_menu_has_one_night_light_item_saying_what_it_does_now(config, now, override, item, choices):
    """Until 0.8.0 a KDE-style "Suspend Night Light" check item stood beside
    the Suspend ▸ submenu, so the menu said the same thing twice, each doing
    something else; at noon it offered to suspend a night light that was off."""
    items, tray = menu_in(config, now, override)
    texts = [a.text() for a in items]
    assert len(texts) == len(set(texts)), texts  # nothing named twice, in any state
    assert texts == ["Open Winlight", item, "Settings…", "Report a Problem…", "Quit"]
    submenu = tray._override_action.menu()
    assert ([a.text() for a in submenu.actions()] if submenu is not None else []) == choices
    assert all(not a.icon().isNull() for a in items)  # each with its icon, as Windows 11's menus have
    tray._controller.shutdown()


@pytest.mark.parametrize(("now", "override"), [(EVENING, "SUSPEND"), (NOON, "ACTIVATE")])
def test_resume_and_turn_off_go_back_to_the_schedule(now, override):
    _items, tray = menu_in(SCHEDULED, now, override)
    tray._override_action.trigger()
    assert tray._controller.override is None
    tray._controller.shutdown()


def test_open_is_the_default_item_and_opens_the_panel_once_the_menu_has_gone(tray):
    from PySide6.QtTest import QTest

    received = []
    tray.panelRequested.connect(received.append)
    assert tray._menu.defaultAction() is tray._open_action  # bold, as Windows marks what clicking the icon does
    tray._open_action.trigger()
    assert received == []  # not while the menu is still closing
    for _ in range(100):
        if received:
            break
        QTest.qWait(10)
    assert len(received) == 1


def test_the_icons_follow_the_menus_text_colour(tray):
    """Drawn in the menu's text colour, again only when that changes: Qt's
    Windows 11 style gives the tray menu Windows' own light or dark look."""
    from PySide6.QtGui import QColor, QPalette

    tray._update_menu()
    before = tray._settings_action.icon().cacheKey()
    tray._update_menu()
    assert tray._settings_action.icon().cacheKey() == before  # same colour: not drawn again
    palette = tray._menu.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#123456"))
    tray._menu.setPalette(palette)
    tray._update_menu()
    assert tray._glyph_color == QColor("#123456") and tray._settings_action.icon().cacheKey() != before
