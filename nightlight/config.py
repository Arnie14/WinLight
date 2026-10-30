# SPDX-License-Identifier: GPL-3.0-only
"""User settings, stored as JSON in the platform's config directory.

Loading is deliberately forgiving: a missing, corrupt or hand-edited file
never stops the app from starting; bad values fall back to defaults.
Settings written by older versions load too (the brightness schedule's
"steps" from 0.1.0 beta 3 and 4 become "points").
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path

import platformdirs

from nightlight.core.settings import (  # the settings model, also importable from here as before
    ACCENTS,
    DEFAULT_SCHEDULE_POINTS,
    DEFAULT_SCHEDULE_TRANSITION,
    MAX_IDLE_MINUTES,
    MAX_SCHEDULE_POINTS,
    MAX_SOLAR_TRANSITION_MINUTES,
    MAX_SUN_OFFSET_MINUTES,
    MAX_TRANSITION_MINUTES,
    NEVER_PAUSE_FROM,
    SUNRISE,
    SUNSET,
    THEMES,
    Anchor,
    AppConfig,
    BrightnessScheduleConfig,
    DisplayPrefs,
    GeneralConfig,
    Mode,
    NightLightConfig,
    SchedulePoint,
    _is_hhmm,
    parse_hhmm,
)
from nightlight.core.shortcuts import Shortcut
from nightlight.files import write_atomic

log = logging.getLogger(__name__)

__all__ = [
    "ACCENTS",
    "CONFIG_VERSION",
    "DATA_FOLDER",
    "DEFAULT_SCHEDULE_POINTS",
    "DEFAULT_SCHEDULE_TRANSITION",
    "MAX_IDLE_MINUTES",
    "MAX_SCHEDULE_POINTS",
    "MAX_SOLAR_TRANSITION_MINUTES",
    "MAX_SUN_OFFSET_MINUTES",
    "MAX_TRANSITION_MINUTES",
    "NEVER_PAUSE_FROM",
    "OLD_DATA_FOLDER",
    "SUNRISE",
    "SUNSET",
    "THEMES",
    "Anchor",
    "AppConfig",
    "BrightnessScheduleConfig",
    "DisplayPrefs",
    "GeneralConfig",
    "Mode",
    "NightLightConfig",
    "SchedulePoint",
    "data_dir",
    "default_path",
    "load",
    "log_dir",
    "parse_hhmm",
    "save",
]

CONFIG_VERSION = 4  # raised whenever settings are added (2: shortcuts, 3: check_for_updates, 4: cycle shortcuts), for _keep_newer

# The folder for settings, state and logs (%LOCALAPPDATA%\WinLight on
# Windows). Versions before 0.3.0 used "night-light"; the first start of a
# newer version renames that folder, so nothing inside it changes.
DATA_FOLDER = "WinLight"
OLD_DATA_FOLDER = "night-light"
# The log file in Logs/, with its rotated copies (WinLight.log.1, .2).
# Before 0.3.0 it was night-light.log; the first start renames those too.
LOG_FILE = "WinLight.log"
OLD_LOG_FILE = "night-light.log"
_data_dir: Path | None = None


def data_dir() -> Path:
    """The settings folder, moved from its old name the first time."""
    global _data_dir
    if _data_dir is None:
        _data_dir = _migrated(Path(platformdirs.user_config_dir(DATA_FOLDER, appauthor=False)),
                              Path(platformdirs.user_config_dir(OLD_DATA_FOLDER, appauthor=False)))
    return _data_dir


def _migrated(new: Path, old: Path) -> Path:
    """Rename `old` to `new` if only `old` exists. If it can't be renamed
    (an older copy still has files open in it), `old` stays in use this
    time and the rename is tried again at the next start."""
    if new.exists() or not old.is_dir():
        return new
    try:
        old.rename(new)
    except OSError as exc:
        log.warning("Could not rename the settings folder %s to %s (%s); using it as it is for now", old.name, new.name, exc)
        return old
    log.info("Renamed the settings folder %s to %s", old.name, new.name)
    return new


def migrate_log_files(folder: Path) -> None:
    """Rename night-light.log and its rotated copies to WinLight.log, .1, .2,
    so the log keeps its history under the new name. Skipped if the new log
    already exists; a file that can't be renamed (an older copy has it
    open) stays, and reports still include it."""
    if (folder / LOG_FILE).exists():
        return
    for old in sorted(folder.glob(OLD_LOG_FILE + "*")):
        new = folder / (LOG_FILE + old.name[len(OLD_LOG_FILE):])
        try:
            old.rename(new)
        except OSError:
            log.debug("Could not rename %s", old.name, exc_info=True)


def is_log_file(name: str) -> bool:
    """A log file of this app, by its current or its old name."""
    return name.startswith((LOG_FILE, OLD_LOG_FILE))


def default_path() -> Path:
    return data_dir() / "settings.json"


def log_dir() -> Path:
    """Where WinLight.log, probe.txt and compatibility.txt go: Logs in
    the settings folder on Windows (so they move with it), the usual log
    folder elsewhere."""
    if sys.platform == "win32":
        return data_dir() / "Logs"
    return Path(platformdirs.user_log_dir(DATA_FOLDER, appauthor=False))


def load(path: Path) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppConfig()
    except (OSError, ValueError):
        log.warning("Could not read %s, using default settings", path, exc_info=True)
        _keep_damaged(path)
        return AppConfig()
    if not isinstance(raw, dict):
        log.warning("Ignoring malformed settings file %s", path)
        _keep_damaged(path)
        return AppConfig()
    try:
        return AppConfig(
            night_light=_from_dict(NightLightConfig, "night_light", raw.get("night_light")).normalized(),
            general=_from_dict(GeneralConfig, "general", raw.get("general")).normalized(),
            brightness_schedule=_schedule_from(raw.get("brightness_schedule")),
            displays=_displays_from(raw.get("displays")),
            shortcuts=_shortcuts_from(raw.get("shortcuts")),
        )
    except Exception:  # a value no check above foresaw: start with defaults rather than not at all
        log.exception("Could not read the settings in %s, using default settings", path)
        _keep_damaged(path)
        return AppConfig()


def _keep_damaged(path: Path) -> None:
    """Copy an unreadable settings file aside before defaults are saved over
    it, so the user's settings can still be recovered by hand."""
    backup = path.with_name(path.name + ".damaged")
    try:
        if path.is_file():
            backup.write_bytes(path.read_bytes())
            log.warning("Kept a copy of the unreadable settings as %s", backup.name)
    except OSError:
        log.warning("Could not keep a copy of the unreadable settings", exc_info=True)


def save(config: AppConfig, path: Path) -> None:
    data = {"version": CONFIG_VERSION, **_to_json(config)}
    _keep_newer(data, path)
    write_atomic(path, json.dumps(data, indent=2))  # a crash mid-write can't leave a truncated file


def _keep_newer(data: dict, path: Path) -> None:
    """When a newer version saved the file, keep what it saved and this one
    doesn't know (a section, or a setting in one), and its version number, so
    they're kept again at each save until that version saves the file itself.
    Going back a version and forward again then loses nothing: LightBulb's
    users lost their hotkeys after updates (#202), and Twinkle Tray keeps a
    copy of its old hotkeys for going back (1.16). A file from an older
    version isn't merged: its retired settings stay retired."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(saved, dict) or not isinstance(saved.get("version"), int) or saved["version"] <= CONFIG_VERSION:
        return
    data["version"] = saved["version"]
    for key, value in saved.items():
        if key not in data:
            data[key] = value
        elif key != "displays" and isinstance(data[key], dict) and isinstance(value, dict):  # displays: keyed by display
            for name, setting in value.items():
                data[key].setdefault(name, setting)


def _from_dict[T](cls: type[T], section: str, data: object) -> T:
    """`cls` from a JSON object, keeping the default for each missing or invalid value."""
    defaults = cls()
    if not isinstance(data, dict):
        return defaults
    values = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        try:
            values[f.name] = _coerce(f.name, data[f.name], getattr(defaults, f.name))
        except (TypeError, ValueError, OverflowError):  # OverflowError: 1e400 reads as infinity
            log.warning("Ignoring invalid setting %s.%s=%r", section, f.name, data[f.name])
    return replace(defaults, **values)


def _schedule_from(data: object) -> BrightnessScheduleConfig:
    """The brightness schedule, from "points" (this version) or "steps" (0.1.0 beta 3 and 4)."""
    if not isinstance(data, dict):
        return BrightnessScheduleConfig()
    scalars = {k: v for k, v in data.items() if k not in ("points", "steps")}
    schedule = _from_dict(BrightnessScheduleConfig, "brightness_schedule", scalars)
    if isinstance(data.get("points"), list):
        points = tuple(_from_dict(SchedulePoint, "brightness_schedule.points", p) for p in data["points"] if isinstance(p, dict))
        schedule = replace(schedule, points=points)
    elif isinstance(data.get("steps"), list):
        points = tuple(point for item in data["steps"] if (point := _point_from_step(item)) is not None)
        # Old schedules had no presets or gradual changes; an empty one gets the default points (and their preset).
        if points and "preset" not in data:
            schedule = replace(schedule, preset="custom")
        schedule = replace(schedule, points=points)
    return schedule.normalized()


def _point_from_step(item: object) -> SchedulePoint | None:
    """A 0.1.0 beta 3/4 step: {"at": "HH:MM" | "sunrise" | "sunset", "level", "offset_minutes"}."""
    if not isinstance(item, dict):
        log.warning("Ignoring invalid brightness step %r", item)
        return None
    at, level, offset = item.get("at", "07:00"), item.get("level", 80), item.get("offset_minutes", 0)
    if not isinstance(level, int) or isinstance(level, bool) or not isinstance(offset, int) or isinstance(offset, bool):
        log.warning("Ignoring invalid brightness step %r", item)
        return None
    if at in (SUNRISE, SUNSET):
        return SchedulePoint(level, anchor=Anchor(at), offset_minutes=offset)
    if isinstance(at, str) and _is_hhmm(at):
        return SchedulePoint(level, at)
    log.warning("Ignoring invalid brightness step %r", item)
    return None


MAX_SHORTCUTS = 32


def _shortcuts_from(data: object) -> tuple[Shortcut, ...]:
    """Each one checked like any other setting; one that can't be used (an
    unknown key, a bare letter, an unknown action) is left out, not fatal."""
    if not isinstance(data, list):
        return ()
    if len(data) > MAX_SHORTCUTS:
        log.warning("Ignoring %d shortcuts past the first %d", len(data) - MAX_SHORTCUTS, MAX_SHORTCUTS)
    shortcuts = []
    for item in data[:MAX_SHORTCUTS]:
        shortcut = _from_dict(Shortcut, "shortcuts", item).normalized() if isinstance(item, dict) else None
        if shortcut is None:
            log.warning("Ignoring a shortcut that can't be used: %r", item)
        else:
            shortcuts.append(shortcut)
    return tuple(shortcuts)


def _displays_from(data: object) -> tuple[DisplayPrefs, ...]:
    if not isinstance(data, dict):
        return ()
    prefs = []
    for key, value in data.items():
        if isinstance(value, dict):
            name = value.get("name") if isinstance(value.get("name"), str) else ""
            hidden = value.get("hidden") if isinstance(value.get("hidden"), bool) else False
            hdr_manual = value.get("hdr_manual") if isinstance(value.get("hdr_manual"), bool) else False
            if name.strip() or hidden or hdr_manual:
                prefs.append(DisplayPrefs(str(key), name.strip(), hidden, hdr_manual))
    return tuple(prefs)


def _to_json(config: AppConfig) -> dict:
    data = asdict(config)
    data["displays"] = {d.key: {"name": d.name, "hidden": d.hidden, "hdr_manual": d.hdr_manual} for d in config.displays}
    data["night_light"]["exempt_apps"] = list(config.night_light.exempt_apps)
    data["general"]["idle_exempt_apps"] = list(config.general.idle_exempt_apps)
    data["brightness_schedule"]["points"] = [asdict(p) for p in config.brightness_schedule.points]
    return data


def _coerce(name: str, value: object, default: object) -> object:
    if name == "mode":
        return Mode(value)
    if name == "anchor":
        return Anchor(value)
    if isinstance(default, tuple):  # a list of strings, such as exempt_apps
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return tuple(value)
        raise TypeError(f"unexpected type for {name}")
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
    elif isinstance(default, (int, float)):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return type(default)(value)
    elif isinstance(default, str) and isinstance(value, str):
        return value
    raise TypeError(f"unexpected type for {name}")


