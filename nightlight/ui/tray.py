# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from nightlight import APP_NAME
from nightlight.color.controller import NightLightController
from nightlight.ui import icons
from nightlight.ui.night_light_text import (
    brightness_status,
    build_override_menu,
    is_night_light_on,
    night_light_status,
    paused_text,
)

# The night light item's icon, by what it does now.
OVERRIDE_GLYPHS = {"Suspend": icons.pause_glyph, "Resume": icons.play_glyph, "Activate": icons.moon_glyph,
                   "Turn Off": icons.sun_glyph}


class Tray(QSystemTrayIcon):
    flyoutRequested = Signal(QRect)  # the icon clicked: the panel opens, or closes if open
    panelRequested = Signal(QRect)  # the menu's Open: the panel opens; the icon's geometry, may be empty
    configureRequested = Signal()
    diagnosticsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, controller: NightLightController) -> None:
        super().__init__()
        self._controller = controller
        self.display_name: Callable[[str], str] | None = None  # set by the app: GDI name -> display name
        self._scheduler = None

        self._menu = QMenu()
        self._override_menu = QMenu()
        # What clicking the icon does, first and in bold, as Windows marks a
        # menu's default: right-clicking by habit finds the panel too.
        self._open_action = self._menu.addAction(icons.app_icon(), f"Open {APP_NAME}", self._open_panel)
        self._menu.setDefaultAction(self._open_action)
        self._menu.addSeparator()
        # One item for night light, saying what it does now: Suspend ▸ or
        # Activate ▸ (for an hour, until the schedule's next change, or until
        # undone), or Resume / Turn Off while one of those is on. Until 0.8.0
        # a KDE-style "Suspend Night Light" check item stood beside it, so the
        # menu read "Suspend Night Light" twice, each doing something else.
        self._override_action = self._menu.addAction("")
        self._override_action.triggered.connect(controller.clear_override)
        self._menu.addSeparator()
        self._settings_action = self._menu.addAction("Settings…", self.configureRequested.emit)
        self._report_action = self._menu.addAction("Report a Problem…", self.diagnosticsRequested.emit)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("Quit", self.quitRequested.emit)
        self._glyph_color: QColor | None = None
        self._override_icons: dict[str, QIcon] = {}
        self._menu.aboutToShow.connect(self._update_menu)
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)
        controller.changed.connect(self._update)
        self._update()
        self._update_menu()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.flyoutRequested.emit(self.geometry())

    def _open_panel(self) -> None:
        # Once the menu has gone: a popup opened as it closes can close with it.
        QTimer.singleShot(0, self, self._request_panel)

    def _request_panel(self) -> None:
        self.panelRequested.emit(self.geometry())

    def _update(self) -> None:
        controller = self._controller
        self.setIcon(icons.app_icon(night=is_night_light_on(controller)))
        paused = paused_text(controller, self.display_name)
        brightness = brightness_status(self._scheduler)
        self.setToolTip(f"{APP_NAME}\nNight Light: {night_light_status(controller)}" + (f"\nBrightness: {brightness}" if brightness else "")
                        + (f"\n{paused}" if paused else ""))

    def set_scheduler(self, scheduler) -> None:
        """Show the brightness schedule too, while it is on."""
        self._scheduler = scheduler
        scheduler.changed.connect(self._update)
        self._update()

    def _update_menu(self) -> None:
        # "Suspend ▸" / "Activate ▸" with KDE's durations, or "Resume" / "Turn Off".
        label = build_override_menu(self._controller, self._override_menu)
        self._override_action.setText(f"{label} Night Light")
        self._override_action.setMenu(None if self._override_menu.isEmpty() else self._override_menu)
        self._draw_glyphs()
        self._override_action.setIcon(self._override_icons[label])

    def _draw_glyphs(self) -> None:
        """The items' icons in the menu's text colour, drawn again only when
        that changes (the theme): light on a dark menu, dark on a light one."""
        color = self._menu.palette().color(QPalette.ColorRole.WindowText)
        if color == self._glyph_color:
            return
        self._glyph_color = color
        self._override_icons = {label: glyph(color) for label, glyph in OVERRIDE_GLYPHS.items()}
        self._settings_action.setIcon(icons.gear_glyph(color))
        self._report_action.setIcon(icons.report_glyph(color))
        self._quit_action.setIcon(icons.power_glyph(color))
