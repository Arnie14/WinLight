# SPDX-License-Identifier: GPL-3.0-only
"""The welcome screen: shown once, at the first start, and again from
Settings > General.

Its job is the few things that decide whether Winlight works well on this
PC, said for this PC rather than in general: when night light comes on
(today's day, as Settings shows it), and what here would clash with it,
found read-only: Windows' own Night Light, other night light and
brightness tools running (f.lux, LightBulb, Twinkle Tray, Monitorian), and
external monitors that don't answer DDC/CI. Each comes with what to do.
If nothing clashes, it says so in one line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from nightlight import APP_NAME, REPO_URL
from nightlight.config import AppConfig, Mode
from nightlight.core.schedule import compute_state
from nightlight.hardware.brightness import MonitorInfo
from nightlight.ui import icons
from nightlight.ui.day_ribbon import DayRibbon
from nightlight.ui.night_light_text import schedule_description
from nightlight.ui.settings_parts import ActionButton, Card, PageTitle, SectionLabel, SettingRow
from nightlight.ui.widgets import SecondaryLabel

SWITCHING_GUIDE_URL = f"{REPO_URL}/blob/main/docs/why-winlight.md#switching-to-winlight"
WINDOWS_NIGHT_LIGHT_URL = "ms-settings:nightlight"
WIDTH = 600

# Other tools that would clash, by the program's name, and what to do about each.
OTHER_TOOLS = {
    "flux.exe": ("f.lux", ("Turn off its night light, or quit it: two night lights tint the screen twice. Its list of "
                           "apps to disable for is Pause night light > Selected apps here.")),
    "lightbulb.exe": ("LightBulb", ("Quit it, and stop it starting with Windows: two night lights tint the screen twice. "
                                    "Its apps to pause for are under Pause night light here.")),
    "twinkle tray.exe": ("Twinkle Tray", ("Quit it, or stop it changing brightness: a monitor sent commands by two apps "
                                          "can ignore both. Its time adjustments are Brightness > Change brightness by "
                                          "time of day here.")),
    "monitorian.exe": ("Monitorian", ("Quit it, or stop it starting with Windows: a monitor sent commands by two apps "
                                      "can ignore both.")),
}
_DDC_CHANNELS = ("ddc", "ddc-high-level", "sdr", "wmi")


@dataclass(frozen=True)
class Finding:
    title: str
    description: str
    action: str = ""  # a button's text, if there is something to open
    url: str = ""  # what it opens


def findings(windows_night_light: bool | None, programs: set[str], monitors: list[MonitorInfo],
             name_of: Callable[[MonitorInfo], str]) -> list[Finding]:
    """What on this PC would clash with Winlight, and what to do about it."""
    found = []
    if windows_night_light:
        found.append(Finding("Windows Night Light is on", "Turn it off: with both on, the screen is tinted twice.",
                             "Turn it off…", WINDOWS_NIGHT_LIGHT_URL))
    for exe, (name, advice) in OTHER_TOOLS.items():
        if exe in programs:
            found.append(Finding(f"{name} is running", advice))
    for monitor in monitors:
        if monitor.internal or monitor.channel in _DDC_CHANNELS:
            continue  # the laptop's panel, or a display already controlled directly
        meanwhile = " Until then it is dimmed through its colors." if monitor.channel == "software" else ""
        found.append(Finding(f"{name_of(monitor)} doesn't answer DDC/CI",
                             "Turn on DDC/CI in the monitor's own menu, then click ⟳ in the panel. Most TVs have no "
                             f"DDC/CI.{meanwhile}"))
    return found


def when_text(config: AppConfig, controller) -> str:
    """When night light comes on, in a sentence or two."""
    night_light = config.night_light
    if not night_light.enabled:
        return "Night light is off. Choose when it comes on in Settings."
    if night_light.mode is Mode.ALWAYS:
        return "Night light is on all the time."
    return schedule_description(controller) or "Night light follows its schedule."


class WelcomeWindow(QWidget):
    """See the module docstring. `open_settings` opens Settings; the window
    closes itself after either button."""

    def __init__(self, controller, config: Callable[[], AppConfig], monitors=None,
                 programs: Callable[[], set[str]] = set, open_settings: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._controller = controller
        self._config = config
        self._monitors = monitors
        self._programs = programs
        self._open_settings = open_settings
        self._windows_night_light: bool | None = None
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWindowIcon(icons.night_icon())
        self.setFixedWidth(WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(6)
        layout.addWidget(PageTitle(f"Welcome to {APP_NAME}", "Night light and brightness for every display, from the tray icon."))
        self.ribbon = DayRibbon(lambda moment: compute_state(controller.config, moment, zone=controller.zone).temperature,
                                controller.now, zone=lambda: controller.zone)
        layout.addWidget(self.ribbon)
        self.when = SecondaryLabel(scale=0.95)
        self.when.setWordWrap(True)
        self.when.setContentsMargins(2, 6, 2, 0)
        layout.addWidget(self.when)

        layout.addWidget(SectionLabel("On this PC"))
        self._card_holder = QVBoxLayout()
        self._card_holder.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._card_holder)
        self.card: Card | None = None
        layout.addSpacing(14)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.guide = ActionButton("How to switch from another app", "subtle")
        self.guide.clicked.connect(self._open_guide)
        self.done = ActionButton("Done", "standard")
        self.done.clicked.connect(self.close)
        self.settings = ActionButton("Open Settings", "accent")
        self.settings.clicked.connect(self._settings_clicked)
        buttons.addWidget(self.guide)
        buttons.addStretch(1)
        buttons.addWidget(self.done)
        buttons.addWidget(self.settings)
        layout.addLayout(buttons)
        if monitors is not None:
            monitors.monitorsChanged.connect(self.refresh)
        self.refresh()

    def set_windows_night_light(self, on: bool | None) -> None:
        if on != self._windows_night_light:
            self._windows_night_light = on
            self.refresh()

    def refresh(self, *_args) -> None:
        """Look again: displays found since, a tool quit, Windows Night Light turned off."""
        config = self._config()
        self.when.setText(when_text(config, self._controller))
        self.ribbon.refresh()
        monitors = list(self._monitors.monitors) if self._monitors is not None else []
        found = findings(self._windows_night_light, self._programs(), monitors,
                         lambda monitor: config.display(monitor.key).name or monitor.name)
        if self.card is not None:
            self._card_holder.removeWidget(self.card)
            self.card.hide()  # at once: until deleted it would still be drawn
            self.card.deleteLater()
        self.card = Card()
        if not found:
            self.card.add(SettingRow("Nothing here clashes with Winlight",
                                     "No other night light or brightness tool is running, and every display answers."))
        for finding in found:
            button = None
            if finding.url:
                button = QPushButton(finding.action)
                button.clicked.connect(lambda _checked=False, url=finding.url: QDesktopServices.openUrl(QUrl(url)))
            self.card.add(SettingRow(finding.title, finding.description, button))
        self._card_holder.addWidget(self.card)
        # Shown now: added to a window already shown, Qt would show it later,
        # and the height below would leave it out.
        self.card.setVisible(True)
        # As tall as the text needs at this width: adjustSize() measures
        # before wrapped descriptions know their height, and cut them off.
        self.setFixedHeight(self.layout().totalHeightForWidth(WIDTH))

    @property
    def found(self) -> list[str]:
        """The titles shown in the card, for tests and the log."""
        return [row.title.text() for row in self.card.findChildren(SettingRow)] if self.card is not None else []

    def _open_guide(self) -> None:
        QDesktopServices.openUrl(QUrl(SWITCHING_GUIDE_URL))

    def _settings_clicked(self) -> None:
        self.close()
        if self._open_settings is not None:
            self._open_settings()
