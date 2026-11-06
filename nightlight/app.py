# SPDX-License-Identifier: GPL-3.0-only
"""Wires the services (monitors, night light, brightness schedule) to the UI (tray, flyout, settings)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer, QTimeZone, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from nightlight import APP_NAME, config
from nightlight.brightness.idle_dim import IdleDimmer
from nightlight.brightness.keys import BrightnessKeys
from nightlight.brightness.memory import BrightnessMemory
from nightlight.brightness.monitors import MonitorManager
from nightlight.brightness.power_source import PowerSourceKeeper
from nightlight.brightness.scheduler import BrightnessScheduler
from nightlight.brightness.wake_report import WakeReport
from nightlight.cli.commands import CommandHandler
from nightlight.color.controller import NightLightController
from nightlight.color.exemptions import ForegroundWatcher
from nightlight.core.brightness_schedule import location_of
from nightlight.core.clock import zone_named
from nightlight.core.schedule import pausing_held
from nightlight.core.shortcuts import (
    BRIGHTNESS_CYCLE,
    BRIGHTNESS_DOWN,
    BRIGHTNESS_SET,
    BRIGHTNESS_UP,
    NIGHT_LIGHT,
    PANEL,
    REFRESH,
    SUSPEND,
    Shortcut,
    cycle_levels,
    next_in_cycle,
)
from nightlight.files import write_atomic
from nightlight.hardware import winsystem
from nightlight.hardware.brightness import BrightnessBackend
from nightlight.hardware.gamma import GammaBackend
from nightlight.hardware.safe_mode import SafeMode
from nightlight.support import compat, diagnostics
from nightlight.system import autostart
from nightlight.system.packaging_info import visible_path
from nightlight.system.shortcuts import ShortcutService
from nightlight.system.updates import UpdateChecker
from nightlight.system.watcher import DisplayWatcher
from nightlight.ui import reveal, theme
from nightlight.ui.flyout import Flyout
from nightlight.ui.night_light_text import night_light_status, toggle_night_light, toggle_suspended
from nightlight.ui.prompt import Prompt
from nightlight.ui.settings_window import SettingsWindow, changed_settings
from nightlight.ui.shortcut_overlay import ShortcutOverlay
from nightlight.ui.tray import Tray
from nightlight.ui.welcome import WelcomeWindow

log = logging.getLogger(__name__)

# When to detect monitors again after a change, in seconds. Monitors can take
# a while to answer DDC/CI after being plugged in or woken, so look more than
# once: Monitorian re-scans over about two minutes after resume (its issue
# #50 was monitors scanned before Windows was ready), Twinkle Tray waits 5 s
# after hardware changes and 8 s after waking. After waking from sleep, see
# wake_report.py (a longer schedule, with timings logged).
RESCAN_AFTER_CHANGE_S = (2, 8)
RESCAN_AFTER_DISPLAYS_ON_S = (3, 8, 20)
# How often to look whether Windows' own Night Light is on (a registry read).
WINDOWS_NIGHT_LIGHT_CHECK_MS = 10_000
# How often to look whether the time zone changed (travel, or changed by
# hand), besides when Windows reports a clock change.
ZONE_CHECK_MS = 60_000
# Deleting old diagnostics zips: a while after start (out of start-up's
# way), then once a day for an app left running.
CLEANUP_DELAY_MS = 60_000
CLEANUP_INTERVAL_MS = 24 * 3600_000
# Hints shown once ever (their names are kept in hints.json next to the settings).
CALIBRATION_HINT = "calibration"
# The welcome screen: shown once ever; due at the first start, until it could be shown.
WELCOME_HINT = "welcome"
WELCOME_DUE = "welcome-due"
HINT_MS = 20_000


def system_zone():
    """The local IANA time zone (Qt maps Windows' zone names), or None.
    Not logged: a time zone tells where the user is (privacy.py)."""
    try:
        return zone_named(QTimeZone.systemTimeZoneId().data().decode("ascii", "replace"))
    except Exception:
        log.debug("Could not read the system time zone", exc_info=True)
        return None


class NightLightApp:
    def __init__(self, qapp: QApplication, brightness: BrightnessBackend, gamma: GammaBackend, config_path: Path) -> None:
        self._qapp = qapp
        self._config_path = config_path
        first_start = not config_path.exists()  # no settings yet: a new install, not an upgrade
        self._config = config.load(config_path)
        self._shut_down = False
        self._quit_reason = ""  # why it is quitting, for the log
        log.info("Settings file: %s", config_path)
        zone = system_zone()
        log.info("Time zone: %s", "known" if zone is not None else "unknown; using the current UTC offset")

        self._gamma = gamma
        if set_journal := getattr(gamma, "set_journal", None):
            set_journal(config_path.with_name("gamma.json"))  # before the first ramp is touched
        general = self._config.general
        # Set up before the monitor thread starts using the backend.
        self._safe_mode = SafeMode(config_path.parent)
        if hasattr(brightness, "safe_mode"):
            brightness.safe_mode = self._safe_mode
        if set_dimming := getattr(brightness, "set_software_dimming", None):
            set_dimming(general.software_dimming)
        if keep := getattr(gamma, "set_keep_calibration", None):
            keep(general.keep_calibration)  # before night light first sets the ramps
        self.monitors = MonitorManager(brightness)
        # Memory before the scheduler: both act on new detections, and the
        # schedule's level, set second, is the one that stands.
        self.brightness_memory = BrightnessMemory(self.monitors, config_path.with_name("brightness.json"), general.remember_brightness)
        self.scheduler = BrightnessScheduler(
            self.monitors, self._config.brightness_schedule, config_path.with_name("schedule.json"), location=self._location, zone=zone
        )
        self.wake_report = WakeReport(self.monitors)
        self.idle_dimmer = IdleDimmer(
            self.monitors,
            self.brightness_memory,
            winsystem.idle_seconds,
            self._idle_held,
            self._hidden_keys,
            gamma,
            scheduler=self.scheduler,
            windows_timeouts=winsystem.screen_timeouts,
        )
        self.power_source = PowerSourceKeeper(self.monitors)
        self.brightness_keys = BrightnessKeys(self.monitors, self._hidden_keys, held=self.power_source.settling)
        # Built without touching the displays; started below, once pausing has
        # looked at the app in front.
        self.controller = NightLightController(gamma, self._config.night_light, zone=zone, start=False)
        self.commands = CommandHandler(self.monitors, self.controller, lambda: self._config, gamma)
        self._settings: SettingsWindow | None = None
        self._welcome: WelcomeWindow | None = None
        self._report_box: Prompt | None = None  # where Report a Problem saved its file
        self._hints_path = config_path.with_name("hints.json")
        self._hints = _load_hints(self._hints_path)
        if first_start and WELCOME_HINT not in self._hints:
            self._hints.add(WELCOME_DUE)  # kept until it could be shown (a fullscreen game at the first start)
        self._windows_night_light: bool | None = None
        self._autostart = autostart.create()
        self._read_autostart()  # only read: writing it at every start set off Defender

        has_tray = QSystemTrayIcon.isSystemTrayAvailable()
        # Wayland doesn't let apps position their own popups, so there the
        # flyout is an ordinary window. Without a tray it's the main window.
        as_window = not has_tray or QGuiApplication.platformName() == "wayland"
        self.flyout = Flyout(self.monitors, self.controller, as_window=as_window)
        self.flyout.configureRequested.connect(self.show_settings)
        self.flyout.set_scheduler(self.scheduler)

        self._exemptions = ForegroundWatcher(winsystem.foreground_app, self._config.night_light,
                                             media=lambda: winsystem.display_required() or winsystem.exclusive_fullscreen(),
                                             held=self._pausing_held)
        self._exemptions.pausedChanged.connect(self.controller.set_paused)
        # Night light on screen now, at once, before the tray and the first
        # window: Windows' set-up of a process's first window took up to 0.9 s
        # on the test laptop, and the start-up fade 3.8 s more. A display paused
        # already (a fullscreen game in front: the watcher's first check) starts neutral.
        self.controller.start(self._exemptions.paused)
        self._apply_preferences(self._config)

        self.tray: Tray | None = None
        if has_tray:
            self.tray = Tray(self.controller)
            self.tray.display_name = self.flyout.display_name_of
            self.tray.set_scheduler(self.scheduler)
            self.tray.flyoutRequested.connect(self._open_flyout)
            self.tray.panelRequested.connect(self._show_flyout)
            self.tray.configureRequested.connect(self.show_settings)
            self.tray.diagnosticsRequested.connect(self.report_problem)
            self.tray.messageClicked.connect(self._on_tray_message_clicked)
            self.tray.quitRequested.connect(self._quit_from_tray)
            self.tray.show()
            qapp.setQuitOnLastWindowClosed(False)
        else:
            log.warning("No system tray available; showing the panel as a window")
            self.flyout.show_near()

        # Display changes Qt sees, and (on Windows) sleep, waking, displays
        # turning off and on, unlocking and clock changes, straight from
        # Windows: gamma ramps are reset then, night light should be back
        # before anyone notices, and nothing goes to sleeping displays.
        self.system_events = winsystem.SystemEvents(qapp)
        self.system_events.endingSession.connect(self._end_session)  # signing out: there may be no later chance
        self.system_events.unlocked.connect(self._on_unlocked)
        # The lock screen turns the screen off sooner (a minute by default): idle dimming plans for it.
        self.system_events.locked.connect(self.idle_dimmer.on_locked)
        self.system_events.unlocked.connect(self.idle_dimmer.on_unlocked)
        self.system_events.displayChanged.connect(self.controller.reapply_now)  # at once; detection follows once settled
        self.system_events.panelBrightness.connect(self._on_panel_brightness)
        # Keyboard shortcuts, registered on the same hidden window.
        self._shortcut_overlay: ShortcutOverlay | None = None  # made the first time it shows
        self.shortcuts = ShortcutService(self.system_events, self._run_shortcut)
        self.shortcuts.set_shortcuts(self._config.shortcuts)
        # Checking for updates: off unless turned on, and never part of start-up.
        self._update_found = ("", "")  # a newer version a check found, and its release page
        self._message_url = ""  # what clicking the tray's last notice opens ("" for a hint)
        self.updates = UpdateChecker()
        self.updates.found.connect(self._on_update_found)
        self.updates.set_enabled(self._config.general.check_for_updates)
        self.system_events.powerSourceChanged.connect(self._on_power_source_changed)
        self._watcher = DisplayWatcher(qapp, events=self.system_events,
                                       idle_seconds=winsystem.idle_seconds if sys.platform == "win32" else None)
        self._watcher.displaysChanged.connect(self._on_displays_plugged)
        self._watcher.suspending.connect(self._on_suspending)
        self._watcher.resumed.connect(self._on_resumed)
        self._watcher.displaysOff.connect(self._on_suspending)
        self._watcher.displaysOn.connect(self._on_displays_on)
        self._watcher.clockChanged.connect(self._on_clock_changed)

        self._night_light_check = QTimer(interval=WINDOWS_NIGHT_LIGHT_CHECK_MS)
        self._night_light_check.timeout.connect(self._check_windows_night_light)
        self._night_light_check.start()
        self._check_windows_night_light()
        self._zone_check = QTimer(interval=ZONE_CHECK_MS)
        self._zone_check.timeout.connect(self._check_zone)
        self._zone_check.start()
        # Old Report a Problem zips are deleted: at start, then daily.
        self._cleanup = QTimer(interval=CLEANUP_INTERVAL_MS)
        self._cleanup.timeout.connect(diagnostics.remove_old_bundles)
        self._cleanup.start()
        QTimer.singleShot(CLEANUP_DELAY_MS, diagnostics.remove_old_bundles)

        qapp.aboutToQuit.connect(self._shutdown)
        self.monitors.monitorsChanged.connect(self._hint_calibration)
        self.monitors.refresh()
        # Last, once everything the settings window uses (the shortcuts among it) exists.
        if self.tray is not None and WELCOME_DUE in self._hints:
            if not self._busy("the welcome screen"):
                self.show_welcome()
            else:
                _save_hints(self._hints_path, self._hints)  # due still: at the next start
        elif self.tray is not None and not self._config.general.start_minimized and not self._busy("the settings at start"):
            self.show_settings()

    # --- Windows and panels ---------------------------------------------------

    def show_panel(self) -> None:
        """Another launch (a shortcut, a hotkey tool) asked for the panel."""
        if self._busy("the panel"):
            return
        self._open_flyout(self.tray.geometry() if self.tray else None)

    def _busy(self, what: str) -> bool:
        """Whether to hold back opening `what` now, so a fullscreen game or
        video keeps its focus (it might otherwise be minimized)."""
        if self._config.general.respect_fullscreen and winsystem.user_busy():
            log.info("Not opening %s over a fullscreen app", what)
            return True
        return False

    def show_welcome(self) -> None:
        """The welcome screen: at the first start, and from Settings > General."""
        if self._welcome is None:
            self._welcome = WelcomeWindow(
                self.controller, lambda: self._config, self.monitors, programs=winsystem.running_programs,
                open_settings=self.show_settings,
                tray_hidden=winsystem.tray_icon_hidden if self.tray is not None else (lambda: None),
                automatic_brightness=winsystem.automatic_brightness_on,
                starts_at_sign_in=self._starts_at_sign_in,
                start_at_sign_in=self._set_start_at_sign_in if self._autostart is not None else None)
        self._welcome.set_windows_night_light(self._windows_night_light)
        self._welcome.refresh()  # a tool may have been quit since
        reveal.show_window(self._welcome)
        if WELCOME_HINT not in self._hints:
            self._hints.add(WELCOME_HINT)
            self._hints.discard(WELCOME_DUE)
            _save_hints(self._hints_path, self._hints)

    def _open_flyout(self, anchor=None) -> None:
        self._check_windows_night_light()
        self.flyout.toggle(anchor)

    def _show_flyout(self, anchor=None) -> None:
        """The tray menu's Open: opens the panel, where clicking the icon
        toggles it (and a toggle just after the panel closed keeps it closed)."""
        self._check_windows_night_light()
        if not self.flyout.isVisible():
            self.flyout.show_near(anchor)

    def _read_autostart(self) -> None:
        """Take "start when I sign in" from Windows: the installer, Task
        Manager or Windows' Settings may have changed it."""
        enabled = autostart.read(self._autostart)
        if enabled is not None and enabled != self._config.general.start_with_windows:
            self._config = replace(self._config, general=replace(self._config.general, start_with_windows=enabled))

    def _starts_at_sign_in(self) -> bool | None:
        return autostart.read(self._autostart)

    def _set_start_at_sign_in(self, on: bool) -> None:
        """The welcome screen's switch: what Settings' own does, applied at once."""
        # Windows' state first: the saved setting can say on where Windows has
        # no entry (the portable zip), and on to on would change nothing.
        self._read_autostart()
        self._apply_settings(replace(self._config, general=replace(self._config.general, start_with_windows=on)),
                             "the welcome screen")
        if self._settings is not None:
            self._settings.take_start_with_windows(on)

    def show_settings(self) -> None:
        if self._settings is None:
            self._read_autostart()
            self._settings = SettingsWindow(
                self.controller,
                self._config,
                can_autostart=self._autostart is not None,
                monitors=self.monitors,
                scheduler=self.scheduler,
                compatibility=self.compatibility,
                report=self.compatibility_report,
                running_apps=winsystem.running_apps,
                report_problem=self.report_problem,
                warmest=getattr(self._gamma, "warmest_accepted", dict),
                display_name=self.flyout.display_name_of,
                reload_calibrations=getattr(self._gamma, "reload_calibrations", None),
                forget_calibrations=getattr(self._gamma, "forget_calibrations", None),
                **self._unlocking(),
                shortcut_status=self.shortcuts.status,
                pause_shortcuts=self.shortcuts.pause,
                check_updates=self.updates.check_now,
                show_welcome=self.show_welcome,
                screen_timeouts=winsystem.screen_timeouts,
            )
            self._settings.applied.connect(self._apply_settings)
            self.shortcuts.changed.connect(self._settings.refresh_shortcut_status)
            self.updates.checked.connect(self._settings.show_update_status)
            version, url = self._update_found
            if url:
                self._settings.show_update_status(f"{version} is available", url)
            elif self.updates.last:
                self._settings.show_update_status(self.updates.last)
        self._settings.set_windows_night_light(self._windows_night_light)
        if self.tray:
            self.flyout.hide()
        reveal.show_window(self._settings)

    def _unlocking(self) -> dict:
        """Unlocking warmer colors, for the settings window: Windows only."""
        if sys.platform != "win32" or not hasattr(self._gamma, "warmest_accepted"):
            return {}
        from nightlight.hardware import win32

        return {"unlock_warmer": self._unlock_warmer_colors, "lock_warmer": self._lock_warmer_colors,
                "warmer_unlocked": win32.gamma_range_expanded}

    def _unlock_warmer_colors(self) -> str:
        """Set GdiIcmGammaRange (after Windows' administrator prompt), then look
        for each display's limit afresh: Windows may accept warmer ramps now."""
        from nightlight.hardware import win32

        outcome = win32.expand_gamma_range(int(self._settings.winId()) if self._settings is not None else 0)
        if outcome == "done":
            if displays_changed := getattr(self._gamma, "displays_changed", None):
                displays_changed()  # forgets the limits found
            self.controller.update()  # applies night light again: a limit that remains is found again
        return outcome

    def _lock_warmer_colors(self) -> str:
        """Remove GdiIcmGammaRange again (after the administrator prompt):
        Windows puts its limit back at the next sign-in."""
        from nightlight.hardware import win32

        return win32.restore_gamma_range(int(self._settings.winId()) if self._settings is not None else 0)

    def compatibility(self) -> list[compat.CompatibilityEntry]:
        warmest = getattr(self._gamma, "warmest_accepted", dict)()
        calibrations = getattr(self._gamma, "calibration_status", dict)()
        return compat.entries(self.monitors.monitors, self.monitors.states, warmest, calibrations)

    def compatibility_report(self) -> str:
        return compat.render(self.compatibility(), compat.system_summary())

    def report_problem(self) -> None:
        """Save a diagnostics zip to the Reports folder, copy a summary, and say
        where it is, in a box like Settings' questions: opened, not exec()'d,
        so no nested event loop (it was an old-style message box until 0.8.0)."""
        title = f"{APP_NAME}: Report a Problem"
        try:
            path, text = diagnostics.write_bundle(self._diagnostics_sources())
        except OSError as exc:
            box = Prompt(None, title, "The diagnostics weren't saved", str(exc))
            box.add_button("Close", "accent", default=True)
            self._open_report_box(box)
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        # Cleared later if it's still ours: nothing lingers on the clipboard.
        QTimer.singleShot(diagnostics.CLIPBOARD_MINUTES * 60_000, lambda: clipboard.text() == text and clipboard.clear())
        box = Prompt(None, title, "Diagnostics saved", (
            f"{path.name}, in {APP_NAME}'s Reports folder. A summary is on the clipboard.\n\n"
            "To report the problem, open an issue on GitHub: describe what happened, paste the summary and attach the file "
            "(Show File opens its folder).\n\n"
            "Nothing personal is included (no names or location), and the folder isn't synced to the cloud. The file is "
            f"deleted after {diagnostics.KEEP_DAYS} days and the clipboard is cleared after {diagnostics.CLIPBOARD_MINUTES} minutes."))
        box.path = path
        box.show_file = box.add_button("Show File", "accent", default=True)
        box.open_issues = box.add_button("Open GitHub Issues")
        box.add_button("Close")
        self._open_report_box(box)

    def _open_report_box(self, box: Prompt) -> None:
        if self._report_box is not None:
            self._report_box.close()  # a second report: its box replaces the first
        box.finished.connect(self._report_answered)
        self._report_box = box
        reveal.show_window(box)

    def _report_answered(self, _result: int) -> None:
        box, self._report_box = self._report_box, None
        if box is None:
            return
        box.deleteLater()
        clicked = box.clicked
        if clicked is None:
            return  # Esc, or replaced by the next report's box
        if clicked is getattr(box, "show_file", None):
            _reveal(box.path)
        elif clicked is getattr(box, "open_issues", None):
            QDesktopServices.openUrl(QUrl(diagnostics.issue_url()))

    def handle_request(self, request: dict, reply) -> None:
        """A request from the command line (winlight-cli)."""
        if request.get("command") == "diagnostics":
            try:
                path, _text = diagnostics.write_bundle(self._diagnostics_sources())
                shown = str(visible_path(path))  # a path the terminal can open, packaged too
                reply({"ok": True, "output": shown, "data": {"path": shown}})
            except OSError as exc:
                reply({"ok": False, "output": f"Could not save the diagnostics: {exc}"})
            return
        try:
            answer = self.commands.handle(request)
        except Exception:  # a bug must still get an answer, not leave the command line waiting
            log.exception("Handling a command-line request failed")
            answer = {"ok": False, "output": "Winlight couldn't do that; see its log for why."}
        reply(answer)
        if request.get("panel") and answer.get("ok"):
            self.show_panel()  # --panel: show the result, unless a game or video is fullscreen

    def _diagnostics_sources(self) -> diagnostics.Sources:
        return diagnostics.Sources(
            monitors=self.monitors,
            controller=self.controller,
            config=lambda: self._config,
            config_path=self._config_path,
            log_dir=config.log_dir(),
            skipped=lambda: set(self._safe_mode.skipped),
            last_wake=lambda: list(self.wake_report.lines),
            compatibility=self.compatibility_report,
            shortcuts=self.shortcuts.report,
        )

    def _on_update_found(self, version: str, url: str) -> None:
        """Say once per version that it's out; the notice opens its release page."""
        self._update_found = (version, url)
        if self._settings is not None:
            self._settings.show_update_status(f"{version} is available", url)
        hint = f"update {version}"
        if self.tray is None or hint in self._hints:
            return
        self._hints.add(hint)
        _save_hints(self._hints_path, self._hints)
        self._message_url = url
        self.tray.showMessage(f"{APP_NAME} {version} is available",
                              "Click to open its page on GitHub, to download it from there.",
                              QSystemTrayIcon.MessageIcon.Information, HINT_MS)

    def _on_tray_message_clicked(self) -> None:
        if self._message_url:
            QDesktopServices.openUrl(QUrl(self._message_url))

    def _on_power_source_changed(self, _source: int) -> None:
        self.power_source.power_source_changed()

    def _on_displays_plugged(self) -> None:
        self._on_displays_changed(RESCAN_AFTER_CHANGE_S)

    def _hint_calibration(self, *_args) -> None:
        """Once ever, when a display with a color calibration is first seen:
        say that night light keeps it, and that Winlight can put it back
        when Windows drops it, if asked to (off by default)."""
        calibrated = getattr(self._gamma, "calibrated", None)
        if (self.tray is None or calibrated is None or CALIBRATION_HINT in self._hints
                or self._config.general.keep_calibration):
            return
        try:
            displays = calibrated()
        except Exception:
            log.debug("Could not tell which displays are calibrated", exc_info=True)
            return
        if not displays or self._busy("a hint about calibrations"):
            return  # asked again at the next detection
        self._hints.add(CALIBRATION_HINT)
        _save_hints(self._hints_path, self._hints)
        name = self.flyout.display_name_of(displays[0])
        self._message_url = ""
        self.tray.showMessage(
            f"{APP_NAME}: a calibrated display",
            f"{name} has a color calibration, and night light keeps it. If Windows drops it (after the screen turns off, say), "
            "Winlight can put it back: Settings > Displays > Keep each display's color calibration.",
            QSystemTrayIcon.MessageIcon.Information,
            HINT_MS,
        )

    # --- Settings -------------------------------------------------------------

    def _location(self) -> tuple[float, float] | None:
        """The Night Light location, which sunrise and sunset schedule points use too."""
        return location_of(self._config.night_light)

    def _idle_held(self) -> bool:
        """Whether not to dim for idle now. Not just because a window is
        fullscreen (a browser or an editor can be): an app keeping the screen
        on (videos, calls, presentations; Windows' display-required state),
        an exclusive-fullscreen game, or an app the user listed in front."""
        if winsystem.display_required() or winsystem.exclusive_fullscreen():
            return True
        listed = self._config.general.idle_exempt_apps
        if listed:
            app = winsystem.foreground_app()
            return bool(app and app.exe in listed)
        return False

    def _pausing_held(self) -> bool:
        """"Never pause late at night" holds now (night light keeps going for
        every app). Only while night light is on: off, there's nothing to pause."""
        controller = self.controller
        return controller.state.night_factor > 0 and pausing_held(controller.config, controller.now(), controller.zone)

    # --- Shortcuts ------------------------------------------------------------

    def _run_shortcut(self, shortcut: Shortcut) -> None:
        """What a keyboard shortcut does, through the same paths as the panel
        and the command line."""
        action = shortcut.action
        if action in (BRIGHTNESS_UP, BRIGHTNESS_DOWN, BRIGHTNESS_SET, BRIGHTNESS_CYCLE):
            self._shortcut_brightness(shortcut)
        elif action == REFRESH:
            self.monitors.retry()  # as the panel's button and `winlight-cli --refresh`
            self._show_shortcut_result(message="Detecting displays again")
        elif action == NIGHT_LIGHT:
            toggle_night_light(self.controller, "a shortcut")
            self._show_shortcut_result(message=f"Night light: {night_light_status(self.controller)}")
        elif action == SUSPEND:
            toggle_suspended(self.controller, "a shortcut")
            self._show_shortcut_result(message=f"Night light: {night_light_status(self.controller)}")
        elif action == PANEL:
            if self.flyout.isVisible():
                self.flyout.hide()  # pressed again: away, as LightBulb's show/hide shortcut (#378)
            else:
                self.show_panel()

    def _shortcut_brightness(self, shortcut: Shortcut) -> None:
        """Each display a step from the level last set (not a reading that may be
        stale, so held keys don't jump: Twinkle Tray #60), clamped on its own,
        so displays keep their difference (#716). The user's own change: it
        stands until the schedule's next point. A display left alone in HDR
        (no automatic DDC/CI writes) changes only when the shortcut names it:
        a shortcut for every display isn't that display's own control."""
        levels = []
        for monitor in self.monitors.monitors:
            state = self.monitors.state(monitor.key)
            if (not monitor.supported or state is None or not state.controllable or self._config.hidden(monitor.key)
                    or (shortcut.display and monitor.key != shortcut.display)
                    or (not shortcut.display and self.monitors.hands_off(monitor.key))):
                continue
            current = self.monitors.value(monitor.key)
            if shortcut.action == BRIGHTNESS_SET:
                target = max(monitor.minimum, min(100, shortcut.value))
            elif shortcut.action == BRIGHTNESS_CYCLE:
                target = next_in_cycle(cycle_levels(shortcut.levels), current, monitor.minimum)
            elif current is None:
                continue
            elif shortcut.action == BRIGHTNESS_UP:
                target = max(current, min(100, current + shortcut.value))  # never lower, even from above 100
            else:
                target = min(current, max(monitor.minimum, current - shortcut.value))  # never higher, even from below the minimum
            if target != current:
                self.monitors.set_brightness(monitor.key, target)
            levels.append((self._config.display(monitor.key).name or monitor.name, target))
        if levels:
            self._show_shortcut_result(levels=levels)

    def _show_shortcut_result(self, levels: list[tuple[str, int]] | None = None, message: str = "") -> None:
        """The overlay, unless it's off, the panel shows it already, or a game
        or presentation is in exclusive fullscreen (Twinkle Tray #83)."""
        if not self._config.general.shortcut_overlay or self.flyout.isVisible() or winsystem.exclusive_fullscreen():
            return
        if self._shortcut_overlay is None:
            self._shortcut_overlay = ShortcutOverlay()
        if levels:
            self._shortcut_overlay.show_levels(levels)
        else:
            self._shortcut_overlay.show_message(message)

    def _hidden_keys(self) -> frozenset[str]:
        """The connected displays the user hid (found under older keys too)."""
        return frozenset(m.key for m in self.monitors.monitors if self._config.hidden(m.key))

    def _apply_settings(self, new: config.AppConfig, source: str = "Settings") -> None:
        old = self._config
        self._config = new
        if changed := changed_settings(new, old):
            log.info("Settings applied, from %s: %s", source, changed)  # names only, never values
        try:
            config.save(new, self._config_path)
        except OSError:
            log.exception("Could not save settings to %s", self._config_path)
        self.controller.set_config(new.night_light)
        if new.general.start_with_windows != old.general.start_with_windows:
            autostart.change(self._autostart, new.general.start_with_windows)
        self.brightness_memory.set_enabled(new.general.remember_brightness)
        if keep := getattr(self._gamma, "set_keep_calibration", None):
            keep(new.general.keep_calibration)
        if new.general.software_dimming != old.general.software_dimming:
            self.monitors.set_software_dimming(new.general.software_dimming)
        self._apply_preferences(new)
        self.scheduler.set_config(new.brightness_schedule)
        if new.shortcuts != old.shortcuts:
            self.shortcuts.set_shortcuts(new.shortcuts)
        if new.general.check_for_updates != old.general.check_for_updates:
            self.updates.set_enabled(new.general.check_for_updates)
        if new.night_light != old.night_light:
            self.scheduler.evaluate("location")  # sunrise and sunset points follow the location

    def _apply_preferences(self, settings: config.AppConfig) -> None:
        """What every part needs from the settings besides night light and the schedule."""
        general = settings.general
        self.flyout.set_linked(general.link_brightness)
        self.brightness_keys.set_enabled(general.follow_laptop_brightness)
        self.power_source.set_enabled(general.keep_brightness_on_power_change)
        self.idle_dimmer.configure(general.idle_dim, general.idle_minutes, general.idle_level)
        self.flyout.set_display_prefs(settings.display)
        self.brightness_memory.set_hidden(settings.hidden)
        self.monitors.set_hdr_manual(lambda key: settings.display(key).hdr_manual)
        self.scheduler.set_hidden(settings.hidden)
        self._exemptions.set_config(settings.night_light)
        theme.apply(general.theme, general.accent)

    # --- Events ---------------------------------------------------------------

    def _check_windows_night_light(self) -> None:
        on = winsystem.windows_night_light_on()
        if on != self._windows_night_light:
            if on:
                log.warning("Windows Night Light is on as well; the two tints stack")
            self._windows_night_light = on
        self.flyout.set_windows_night_light(on)
        if self._welcome is not None:
            self._welcome.set_windows_night_light(on)
        if self._settings is not None:
            self._settings.set_windows_night_light(on)

    def _on_suspending(self) -> None:
        # Nothing goes to the displays while the PC sleeps or the screens are
        # off: DDC/CI can wake a sleeping monitor or hang its firmware.
        self.monitors.suspend()
        self._set_displays_off(True)

    def _set_displays_off(self, off: bool) -> None:
        """Gamma checks and watching the app in front, rarely while nothing is
        on screen (LightBulb #419: no work while the displays are off), as
        usual again once they are on."""
        self.controller.set_displays_off(off)
        self._exemptions.set_displays_off(off)

    def _on_resumed(self) -> None:
        # Windows' event and the clock check can both report one wake; the
        # wake report follows it once (and schedules detection, logging when
        # each display answers again).
        new_wake = self.wake_report.woke()
        self._set_displays_off(False)
        if self.monitors.paused:
            self.monitors.resume(() if new_wake else RESCAN_AFTER_CHANGE_S)
        if not new_wake:
            return
        # Monitors and laptop panels often wake at another brightness, and a
        # schedule point may have passed while asleep (only the latest applies).
        self.controller.reapply_now()
        self.brightness_memory.restore_all_soon()
        self._reapply_colors()
        self.scheduler.evaluate("wake")

    def _on_displays_on(self) -> None:
        # The screen timeout ended without the PC sleeping: no display change
        # is reported, but ramps and levels may have been reset (Monitorian
        # re-checks then too), and DisplayPort monitors often drop out while
        # off; detection brings them back.
        self._set_displays_off(False)
        if self.monitors.paused:
            self.monitors.resume(RESCAN_AFTER_DISPLAYS_ON_S)
        else:
            self.monitors.refresh_later(RESCAN_AFTER_DISPLAYS_ON_S)
        self.controller.reapply_now()
        self.brightness_memory.restore_all_soon()
        self._reapply_colors()

    def _on_panel_brightness(self, level: int) -> None:
        """Windows reported the built-in display's level: its power plan's for a
        new power source (put back), or the keys or its slider (followed)."""
        if not self.power_source.absorbs(level):
            self.brightness_keys.on_windows_event(level)

    def _on_unlocked(self) -> None:
        self._set_displays_off(False)  # someone is at the screen, whatever was missed
        self.controller.reapply_now()

    def _on_clock_changed(self) -> None:
        if not self._check_zone():
            self.controller.update()
            self.scheduler.evaluate("clock")

    def _check_zone(self) -> bool:
        """Follow a change of time zone: both schedules are laid out in it.
        True if it changed (and the schedules were brought up to date)."""
        zone = system_zone()
        if zone is None or zone == self.controller.zone:
            return False
        log.info("The time zone changed; both schedules follow it")  # which one isn't logged (privacy.py)
        self.controller.zone = self.scheduler.zone = zone
        self.controller.update()
        self.scheduler.evaluate("time zone")
        return True

    def _on_displays_changed(self, rescan_after_s: tuple[float, ...]) -> None:
        self._reapply_colors()
        self.controller.reapply_now()
        self.monitors.refresh_later(rescan_after_s)

    def _reapply_colors(self) -> None:
        # Display changes and sleep can reset gamma ramps: re-apply now.
        if displays_changed := getattr(self._gamma, "displays_changed", None):
            displays_changed()
        self.controller.update()

    def quit(self, reason: str) -> None:
        """Quit, saying why in the log."""
        self._quit_reason = reason
        self._qapp.quit()

    def _quit_from_tray(self) -> None:
        self.quit("Quit in the tray menu")

    def quit_when_asked(self) -> None:
        """Another launch's --quit: the installer, the uninstaller or a script."""
        self.quit("asked to by --quit (the installer, the uninstaller or a script)")

    def _end_session(self) -> None:
        self._quit_reason = "Windows is ending the session (signing out, restarting or shutting down)"
        self._shutdown()

    def _shutdown(self) -> None:
        if self._shut_down:
            return  # quitting after signing out started it already
        self._shut_down = True
        # A line at the start and one at the end: without them a log can't
        # tell a clean quit from a crash or a power cut (testers' reports).
        log.info("Quitting: %s", self._quit_reason or "asked to quit")
        started, failed = time.monotonic(), []
        steps = (
            ("stopping the timers", lambda: (self._night_light_check.stop(), self._zone_check.stop(), self._cleanup.stop())),
            ("stopping the display watcher", self._watcher.stop),  # signing out keeps the event loop running: no late display events
            ("stopping the laptop-key follower", lambda: self.brightness_keys.set_enabled(False)),
            ("stopping pausing", self._exemptions.stop),
            # Quitting while dimmed: levels back first (queued before the monitor thread stops).
            ("undoing idle dimming", self.idle_dimmer.release),
            ("stopping the brightness schedule", self.scheduler.shutdown),
            ("giving the displays their colors back", self.controller.shutdown),
            ("saving the brightness levels", self.brightness_memory.shutdown),
            ("stopping the monitor thread", self.monitors.shutdown),
            ("letting go of the shortcuts", self.shortcuts.stop),
            ("stopping the update check", lambda: self.updates.set_enabled(False)),  # no check while the session ends
            ("closing Windows' notifications", self.system_events.close),
        )
        # Each on its own: one that fails mustn't skip the rest, the colors above all.
        for what, step in steps:
            try:
                step()
            except Exception:
                failed.append(what)
                log.exception("Quitting: %s failed; carrying on", what)
        took = time.monotonic() - started
        if failed:
            log.warning("Quit in %.1f s, but %s failed", took, " and ".join(failed))
        else:
            log.info("Quit cleanly in %.1f s: colors back to normal, levels saved", took)


def _load_hints(path: Path) -> set[str]:
    try:
        names = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError):
        log.debug("Could not read %s", path.name, exc_info=True)
        return set()
    return {name for name in names if isinstance(name, str)} if isinstance(names, list) else set()


def _save_hints(path: Path, hints: set[str]) -> None:
    try:
        write_atomic(path, json.dumps(sorted(hints)))
    except OSError:
        log.debug("Could not save %s", path.name, exc_info=True)


def _reveal(path: Path) -> None:
    """Show a file in Explorer (selected), or its folder elsewhere."""
    path = visible_path(path)  # in the Store package, where Windows really put it
    if sys.platform == "win32":
        # By its full path: by bare name, Windows looks in the app's folder and
        # the current folder first, where anyone could have left an explorer.exe.
        explorer = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "explorer.exe"
        subprocess.Popen([str(explorer), "/select,", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
