# SPDX-License-Identifier: GPL-3.0-only
"""The settings model: what each setting is, its default and its valid
range. Pure data, so the schedules in core can use it; reading and saving
the settings file is config.py's.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time
from enum import StrEnum

from nightlight.core.colortemp import MAX_KELVIN, MIN_KELVIN
from nightlight.core.shortcuts import Shortcut

MAX_TRANSITION_MINUTES = 600
MAX_IDLE_MINUTES = 240
MAX_SOLAR_TRANSITION_MINUTES = 120
THEMES = ("system", "light", "dark")
# When "never pause late at night" begins: as the evening transition starts,
# once night light is fully on, or at a set time (bedtime, say).
NEVER_PAUSE_FROM = ("evening", "night", "time")
ACCENTS = ("windows", "amber", "blue", "teal", "green", "purple", "rose")  # colors in ui/theme.py


class Mode(StrEnum):
    """When night light switches on, mirroring KDE's "Switching times"."""

    LOCATION = "location"  # sunset and sunrise at a manual location
    TIMES = "times"  # custom times
    ALWAYS = "always"  # always on night light


@dataclass(frozen=True)
class NightLightConfig:
    enabled: bool = False
    mode: Mode = Mode.TIMES
    day_temperature: int = 6500
    night_temperature: int = 4500
    transition_minutes: int = 30
    night_start: str = "18:00"  # HH:MM, when the evening transition begins
    day_start: str = "06:00"  # HH:MM, when the morning transition begins
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = ""  # IANA zone the location was picked from; "" for a custom location
    # Pause night light on the display showing these apps (f.lux's "disable
    # for" list): lower-case executable names such as "photoshop.exe".
    exempt_apps: tuple[str, ...] = ()
    exempt_fullscreen: bool = False  # pause it on a display while any app is fullscreen there (games, video)
    pause_for_apps: bool = True  # pause it for exempt_apps (a switch of its own; the list is kept while off)
    # Pause it, as Winlight judges from what Windows reports, for video,
    # calls and games (an app keeping the screen on, exclusive fullscreen)
    # and for known color-critical apps (exemptions.COLOR_APPS).
    pause_automatically: bool = False
    # Sunrise and sunset: how long the change takes. -1 follows twilight
    # (sunset to civil dusk, dawn to sunrise, about 30 min); 0 is instant.
    solar_transition_minutes: int = -1
    # Late at night none of the above pause night light, for sleep's sake:
    # from never_pause_from (NEVER_PAUSE_FROM; "time": never_pause_time)
    # until the morning transition starts.
    never_pause_at_night: bool = False
    never_pause_from: str = "night"
    never_pause_time: str = "22:00"  # HH:MM

    def normalized(self) -> NightLightConfig:
        defaults = NightLightConfig()
        return replace(
            self,
            day_temperature=_clamp(self.day_temperature, MIN_KELVIN, MAX_KELVIN),
            night_temperature=_clamp(self.night_temperature, MIN_KELVIN, MAX_KELVIN),
            transition_minutes=_clamp(self.transition_minutes, 0, MAX_TRANSITION_MINUTES),
            night_start=self.night_start if _is_hhmm(self.night_start) else defaults.night_start,
            day_start=self.day_start if _is_hhmm(self.day_start) else defaults.day_start,
            latitude=_clamp(self.latitude, -90.0, 90.0),
            longitude=_clamp(self.longitude, -180.0, 180.0),
            exempt_apps=tuple(sorted({app.strip().lower() for app in self.exempt_apps if app.strip()})),
            solar_transition_minutes=-1 if self.solar_transition_minutes < 0 else _clamp(self.solar_transition_minutes, 0, MAX_SOLAR_TRANSITION_MINUTES),
            never_pause_from=self.never_pause_from if self.never_pause_from in NEVER_PAUSE_FROM else defaults.never_pause_from,
            never_pause_time=self.never_pause_time if _is_hhmm(self.never_pause_time) else defaults.never_pause_time,
        )


@dataclass(frozen=True)
class GeneralConfig:
    start_with_windows: bool = True  # start when the user signs in
    start_minimized: bool = True  # start in the tray only, without opening the settings
    remember_brightness: bool = True  # restore each monitor's level after start, sleep and reconnecting
    link_brightness: bool = False  # one slider moves every monitor's brightness
    software_dimming: bool = True  # dim displays without brightness control (TVs) through the gamma ramp
    # Don't open windows unasked (a second launch's panel, settings at sign-in)
    # while a game, video or presentation is fullscreen: that can minimize it.
    respect_fullscreen: bool = True
    # External displays follow the laptop panel's level (its brightness keys).
    follow_laptop_brightness: bool = False
    # Dim every display after this many minutes without input (Twinkle Tray's
    # idle detection), not while a video, game or presentation keeps it on.
    idle_dim: bool = False
    idle_minutes: int = 5
    idle_level: int = 20
    # Never dim for idle while one of these apps is in front (a call, a video
    # in a player that doesn't keep the screen on): lower-case exe names.
    idle_exempt_apps: tuple[str, ...] = ()
    # Put the built-in display's level back when Windows changes it for being
    # plugged in or unplugged (brightness/power_source.py).
    keep_brightness_on_power_change: bool = False
    # Put each display's color calibration back when Windows drops it (e.g.
    # after the screen turns off and on), as calibration loaders do.
    keep_calibration: bool = False
    # Show the new level (or night light's state) on screen when a shortcut is used.
    shortcut_overlay: bool = True
    # Ask GitHub once a day whether a newer version is out (system/updates.py):
    # Winlight's only connection to the internet, so off unless turned on.
    check_for_updates: bool = False
    theme: str = "system"  # "system" (follow Windows), "light" or "dark"
    accent: str = "windows"  # Windows' accent colour, or one of ACCENTS

    def normalized(self) -> GeneralConfig:
        # The same ranges as the settings window's fields.
        return replace(
            self,
            idle_minutes=_clamp(self.idle_minutes, 1, MAX_IDLE_MINUTES),
            idle_level=_clamp(self.idle_level, 0, 100),
            idle_exempt_apps=tuple(sorted({app.strip().lower() for app in self.idle_exempt_apps if app.strip()})),
            theme=self.theme if self.theme in THEMES else "system",
            accent=self.accent if self.accent in ACCENTS else "windows",
        )


class Anchor(StrEnum):
    """What a brightness schedule point's time is relative to."""

    CLOCK = "clock"  # a time of day
    SUNRISE = "sunrise"
    SUNSET = "sunset"


# Kept for code and settings from 0.1.0 beta 3 and 4, which wrote "at": "sunrise".
SUNRISE, SUNSET = Anchor.SUNRISE.value, Anchor.SUNSET.value
MAX_SUN_OFFSET_MINUTES = 240
MAX_SCHEDULE_POINTS = 12


@dataclass(frozen=True)
class SchedulePoint:
    """From this moment on, displays are set to `level` (until the next point)."""

    level: int = 100
    at: str = "07:00"  # HH:MM, for Anchor.CLOCK
    anchor: Anchor = Anchor.CLOCK
    offset_minutes: int = 0  # before (-) or after (+) sunrise or sunset

    def normalized(self) -> SchedulePoint:
        return replace(
            self,
            level=_clamp(self.level, 0, 100),
            at=self.at if _is_hhmm(self.at) else "07:00",
            offset_minutes=_clamp(self.offset_minutes, -MAX_SUN_OFFSET_MINUTES, MAX_SUN_OFFSET_MINUTES),
        )


DEFAULT_SCHEDULE_POINTS = (SchedulePoint(100, "07:00"), SchedulePoint(50, "20:00"))
DEFAULT_SCHEDULE_TRANSITION = 30  # the "Day and night" preset's


@dataclass(frozen=True)
class BrightnessScheduleConfig:
    """Brightness by time of day, like Twinkle Tray's time adjustments."""

    enabled: bool = False
    preset: str = "day_night"  # the preset the points came from, or "custom"
    points: tuple[SchedulePoint, ...] = DEFAULT_SCHEDULE_POINTS
    transition_minutes: int = DEFAULT_SCHEDULE_TRANSITION  # 0: change at each point (with a short fade); else gradually

    def normalized(self) -> BrightnessScheduleConfig:
        points = tuple(p.normalized() for p in self.points[:MAX_SCHEDULE_POINTS]) or DEFAULT_SCHEDULE_POINTS
        return replace(self, points=points, transition_minutes=_clamp(self.transition_minutes, 0, MAX_TRANSITION_MINUTES))


@dataclass(frozen=True)
class DisplayPrefs:
    """A display's custom name and visibility, keyed by MonitorInfo.key (as Twinkle Tray keys them)."""

    key: str
    name: str = ""  # "" keeps the display's own name
    hidden: bool = False  # left out of the panel, linked changes and the brightness schedule
    # While HDR is on, only the user's own slider changes it over DDC/CI: no
    # restoring, schedule or following the laptop's keys. Some monitors show a
    # tint after DDC/CI brightness changes in HDR mode (Twinkle Tray #1310).
    hdr_manual: bool = False


@dataclass(frozen=True)
class AppConfig:
    night_light: NightLightConfig = field(default_factory=NightLightConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)
    brightness_schedule: BrightnessScheduleConfig = field(default_factory=BrightnessScheduleConfig)
    displays: tuple[DisplayPrefs, ...] = ()
    shortcuts: tuple[Shortcut, ...] = ()

    def display(self, key: str) -> DisplayPrefs:
        """A display's preferences, also when saved under its key from an
        older version (the hardware id without the serial)."""
        exact = next((d for d in self.displays if d.key == key), None)
        if exact is not None:
            return exact
        legacy = key.split(":", 1)[0]
        return next((replace(d, key=key) for d in self.displays if d.key == legacy and legacy != key), DisplayPrefs(key))

    def hidden(self, key: str) -> bool:
        """Whether a display is hidden; always ask this way (it knows the older keys)."""
        return self.display(key).hidden


def parse_hhmm(text: str) -> time:
    return datetime.strptime(text, "%H:%M").time()


def _clamp(value, low, high):
    return max(low, min(high, value))


def _is_hhmm(text: str) -> bool:
    try:
        parse_hhmm(text)
    except (TypeError, ValueError):
        return False
    return True
