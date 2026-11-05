# SPDX-License-Identifier: GPL-3.0-only
"""The welcome screen: shown once, at the first start, and again from
Settings > General.

Its job is the few things that decide whether Winlight works well on this
PC, said for this PC rather than in general: when night light comes on
(today's day, as Settings shows it); each display and how Winlight controls
it (with what to do for one that doesn't answer DDC/CI, and a word on HDR,
where Windows doesn't let night light tint it); what here would clash with
it, found read-only: Windows' own Night Light, other night light and
brightness tools running; and two tips: Winlight's tray icon hidden under
^, and starting at sign-in, where it doesn't yet. If nothing clashes, it
says so in one line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from nightlight import APP_NAME, REPO_URL
from nightlight.config import AppConfig, Mode
from nightlight.core.schedule import compute_state
from nightlight.hardware.brightness import MonitorInfo
from nightlight.ui import icons
from nightlight.ui.day_ribbon import DayRibbon
from nightlight.ui.night_light_text import schedule_description
from nightlight.ui.settings_parts import ActionButton, Card, PageTitle, SectionLabel, SettingRow, ToggleSwitch
from nightlight.ui.widgets import CHANNEL_CAPTIONS, SecondaryLabel

SWITCHING_GUIDE_URL = f"{REPO_URL}/blob/main/docs/why-winlight.md#switching-to-winlight"
WINDOWS_NIGHT_LIGHT_URL = "ms-settings:nightlight"
TASKBAR_SETTINGS_URL = "ms-settings:taskbar"
WIDTH = 600
_MARGIN = 28  # left and right
# Room kept for the title bar and a margin, on a screen too short for everything.
SCREEN_ALLOWANCE = 80
MIN_CARDS_HEIGHT = 200
# Explorer records a new tray icon a moment after it first appears: if the
# welcome screen looked too soon, it looks once more.
TRAY_RECHECK_MS = 3000

_TINTS_TWICE = "two night lights tint the screen twice."
_IGNORES_BOTH = "a monitor sent commands by two apps can ignore both."
# Other tools that would clash: their name, their programs (lower case;
# * for a version in the name), and what to do about each.
OTHER_TOOLS = (
    ("f.lux", ("flux.exe",), ("Turn off its night light, or quit it: " + _TINTS_TWICE + " Its list of apps to disable "
                              "for is Pause night light > Selected apps here.")),
    ("LightBulb", ("lightbulb.exe",), ("Quit it, and stop it starting with Windows: " + _TINTS_TWICE + " Its apps to "
                                       "pause for are under Pause night light here.")),
    ("Twinkle Tray", ("twinkle tray.exe",), ("Quit it, or stop it changing brightness: " + _IGNORES_BOTH + " Its time "
                                             "adjustments are Brightness > Change brightness by time of day here.")),
    ("Monitorian", ("monitorian.exe",), "Quit it, or stop it starting with Windows: " + _IGNORES_BOTH),
    ("Iris", ("iris.exe",), "Turn off its color and brightness changes, or quit it: " + _TINTS_TWICE),
    ("CareUEyes", ("careueyes.exe", "careueyesportable.exe"),
     "Turn off its filter and dimming, or quit it: " + _TINTS_TWICE),
    ("ClickMonitorDDC", ("clickmonitorddc*.exe",), "Quit it: " + _IGNORES_BOTH),
    ("Dell Display Manager", ("ddpm.exe", "ddm.exe"), "Quit it, or stop it changing brightness: " + _IGNORES_BOTH),
    ("LG OnScreen Control", ("onscreen control.exe",), "Quit it, or stop it changing brightness: " + _IGNORES_BOTH),
)
_DDC_CHANNELS = ("ddc", "ddc-high-level", "sdr", "wmi")
_TURN_ON_DDC = "Turn on DDC/CI in the monitor's own menu, then click ⟳ in the panel. Most TVs have no DDC/CI."


@dataclass(frozen=True)
class Finding:
    title: str
    description: str
    action: str = ""  # a button's text, if there is something to open
    url: str = ""  # what it opens


def findings(windows_night_light: bool | None, programs: set[str]) -> list[Finding]:
    """What on this PC would clash with Winlight, and what to do about it."""
    found = []
    if windows_night_light:
        found.append(Finding("Windows Night Light is on", "Turn it off: with both on, the screen is tinted twice.",
                             "Turn it off…", WINDOWS_NIGHT_LIGHT_URL))
    for name, patterns, advice in OTHER_TOOLS:
        if any(fnmatchcase(program, pattern) for program in programs for pattern in patterns):
            found.append(Finding(f"{name} is running", advice))
    return found


def tray_tip(hidden: bool | None) -> Finding | None:
    """Windows 11 puts a new tray icon under ^, where a tray app is easy to lose."""
    if not hidden:
        return None
    return Finding(f"{APP_NAME}'s icon is under ^ next to the clock",
                   f"Windows 11 hides new tray icons there. To keep {APP_NAME}'s in sight, turn it on under "
                   "Other system tray icons.", "Taskbar settings…", TASKBAR_SETTINGS_URL)


def display_lines(monitors: list[MonitorInfo], name_of: Callable[[MonitorInfo], str]) -> list[Finding]:
    """Each display and how Winlight controls it, in the panel's words, with
    what to do for one that doesn't answer DDC/CI."""
    lines = []
    for monitor in monitors:
        if monitor.control == "sdr":
            how = "HDR is on, so its brightness is Windows' brightness for SDR content."
        elif monitor.supported and (monitor.internal or monitor.channel in _DDC_CHANNELS):
            caption = CHANNEL_CAPTIONS.get(monitor.channel)
            how = f"{caption[0]}: {caption[1][:1].lower()}{caption[1][1:]}" if caption else "Brightness control works."
        elif monitor.supported:
            how = f"Doesn't answer DDC/CI, so it is dimmed through its colors for now. {_TURN_ON_DDC}"
        else:
            how = f"Doesn't answer DDC/CI, so it has no brightness control. {_TURN_ON_DDC}"
        if monitor.hdr:
            # Windows applies no gamma ramp to a display in HDR.
            how += (" Night light can't tint it until HDR is off: Windows doesn't allow it." if monitor.control == "sdr"
                    else " HDR is on: night light can't tint it until HDR is off, as Windows doesn't allow it.")
        lines.append(Finding(name_of(monitor), how))
    return lines


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
                 programs: Callable[[], set[str]] = set, open_settings: Callable[[], None] | None = None,
                 tray_hidden: Callable[[], bool | None] = lambda: None,
                 starts_at_sign_in: Callable[[], bool | None] = lambda: None,
                 start_at_sign_in: Callable[[bool], None] | None = None) -> None:
        super().__init__()
        self._controller = controller
        self._config = config
        self._monitors = monitors
        self._programs = programs
        self._open_settings = open_settings
        self._tray_hidden = tray_hidden
        self._starts_at_sign_in = starts_at_sign_in
        self._start_at_sign_in = start_at_sign_in
        self._windows_night_light: bool | None = None
        # Offered once it's found off, and kept while the window is open: a
        # switch mustn't vanish as it's turned on.
        self._offer_sign_in = False
        self.sign_in = ToggleSwitch(f"Start {APP_NAME} when I sign in")
        self.sign_in.toggled.connect(self._sign_in_toggled)
        self._tray_recheck = QTimer(self, singleShot=True, interval=TRAY_RECHECK_MS)
        self._tray_recheck.timeout.connect(self._look_again)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWindowIcon(icons.app_icon())
        self.setFixedWidth(WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, 24, _MARGIN, 20)
        layout.setSpacing(6)
        layout.addWidget(PageTitle(f"Welcome to {APP_NAME}", "Night light and brightness for every display, from the tray icon."))
        self.ribbon = DayRibbon(lambda moment: compute_state(controller.config, moment, zone=controller.zone).temperature,
                                controller.now, zone=lambda: controller.zone)
        layout.addWidget(self.ribbon)
        self.when = SecondaryLabel(scale=0.95)
        self.when.setWordWrap(True)
        self.when.setContentsMargins(2, 6, 2, 0)
        layout.addWidget(self.when)

        # The cards scroll, on a screen too short for all of them (four
        # displays and three tips need about 910 px; a 1366x768 laptop shows
        # about 730); the title and the buttons stay in view.
        self._cards = QWidget()
        cards = QVBoxLayout(self._cards)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(6)
        cards.addWidget(SectionLabel("Your displays"))
        self._displays_holder = QVBoxLayout()
        self._displays_holder.setContentsMargins(0, 0, 0, 0)
        cards.addLayout(self._displays_holder)
        self.displays_card: Card | None = None
        cards.addWidget(SectionLabel("On this PC"))
        self._card_holder = QVBoxLayout()
        self._card_holder.setContentsMargins(0, 0, 0, 0)
        cards.addLayout(self._card_holder)
        self.card: Card | None = None
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self._cards)
        layout.addWidget(self.scroll)
        layout.addSpacing(14)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.guide = ActionButton("How to switch from another app", "link")  # opens a page in the browser
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
            monitors.monitorsChanged.connect(self._on_monitors_changed)
        self.refresh()

    def _on_monitors_changed(self, *_args) -> None:
        if self.isVisible():  # closed, nobody sees it: refresh() runs when it's shown again
            self.refresh()

    def set_windows_night_light(self, on: bool | None) -> None:
        if on != self._windows_night_light:
            self._windows_night_light = on
            if self.isVisible():
                self.refresh()

    def refresh(self, *_args) -> None:
        """Look again: displays found since, a tool quit, Windows Night Light turned off."""
        config = self._config()
        self.when.setText(when_text(config, self._controller))
        self.ribbon.refresh()
        monitors = list(self._monitors.monitors) if self._monitors is not None else []
        displays = Card()
        for line in display_lines(monitors, lambda monitor: config.display(monitor.key).name or monitor.name):
            displays.add(SettingRow(line.title, line.description))
        if not monitors:
            displays.add(SettingRow("Looking for displays…", "Each is listed here as soon as it answers."))
        self.displays_card = self._replace(self._displays_holder, self.displays_card, displays)

        card = Card()
        found = findings(self._windows_night_light, self._programs())
        if not found:
            card.add(SettingRow("Nothing here clashes with Winlight", "No other night light or brightness tool is "
                                "running, and Windows Night Light is off."))
        hidden = self._tray_hidden()
        if hidden is None and self.isVisible() and not self._tray_recheck.isActive():
            self._tray_recheck.start()  # a new icon: Explorer may not have recorded it yet
        if tip := tray_tip(hidden):
            found.append(tip)
        for finding in found:
            button = None
            if finding.url:
                button = QPushButton(finding.action)
                button.clicked.connect(lambda _checked=False, url=finding.url: QDesktopServices.openUrl(QUrl(url)))
            card.add(SettingRow(finding.title, finding.description, button))
        if self._start_at_sign_in is not None and (self._offer_sign_in or self._starts_at_sign_in() is False):
            self._offer_sign_in = True
            card.add(SettingRow(f"Start {APP_NAME} when I sign in", "It doesn't yet, so night light and its schedule "
                                f"wait until you open {APP_NAME}. Settings has this switch too.", self.sign_in))
            self.sign_in.show()  # taken out of the old card, it was hidden; it has a parent again now
        self.card = self._replace(self._card_holder, self.card, card)
        self._fit()

    def _fit(self) -> None:
        """As tall as the text needs at this width (adjustSize() measures
        before wrapped descriptions know their height, and cut them off), or
        as the screen allows, the cards scrolling."""
        cards = self._cards.layout().totalHeightForWidth(WIDTH - 2 * _MARGIN)
        self.scroll.setFixedHeight(cards)
        needed = self.layout().totalHeightForWidth(WIDTH)
        if (over := needed - (self._screen_height() - SCREEN_ALLOWANCE)) > 0:
            self.scroll.setFixedHeight(max(MIN_CARDS_HEIGHT, cards - over))
            needed = self.layout().totalHeightForWidth(WIDTH)
        self.setFixedHeight(needed)

    def _screen_height(self) -> int:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry().height() if screen is not None else 10_000

    def _replace(self, holder: QVBoxLayout, old: Card | None, new: Card) -> Card:
        """Put `new` where `old` was, shown at once: added to a window already
        shown, Qt would show it later, and the height would leave it out."""
        if old is not None:
            if self.sign_in.parent() is not None and old.isAncestorOf(self.sign_in):
                self.sign_in.setParent(None)  # kept: it moves to the new card
            holder.removeWidget(old)
            old.hide()  # at once: until deleted it would still be drawn
            old.deleteLater()
        holder.addWidget(new)
        new.setVisible(True)
        return new

    def _look_again(self) -> None:
        if self.isVisible():
            self.refresh()

    def _sign_in_toggled(self, on: bool) -> None:
        if self._start_at_sign_in is not None:
            self._start_at_sign_in(on)

    @property
    def found(self) -> list[str]:
        """The titles shown under "On this PC", for tests and the log."""
        return [row.title.text() for row in self.card.findChildren(SettingRow)] if self.card is not None else []

    @property
    def displays(self) -> list[tuple[str, str]]:
        """Each display's row: its name and what is said about it."""
        rows = self.displays_card.findChildren(SettingRow) if self.displays_card is not None else []
        return [(row.title.text(), row.description.text()) for row in rows]

    def _open_guide(self) -> None:
        QDesktopServices.openUrl(QUrl(SWITCHING_GUIDE_URL))

    def _settings_clicked(self) -> None:
        self.close()
        if self._open_settings is not None:
            self._open_settings()
