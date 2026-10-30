# SPDX-License-Identifier: GPL-3.0-only
"""Installed apps, for picking them by name in the app lists (pausing night
light for an app, never dimming while one is in front) instead of hunting
for an .exe file.

Read from the Start menu's shortcuts (the current user's and everyone's):
each points at the program it starts. Only read, never changed. Shortcuts
that point elsewhere (a web page, a folder, a document) or at an
uninstaller are left out; Store apps have no shortcut there and are picked
from the running apps instead.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Shortcuts named like these aren't apps anyone pauses night light for.
NOT_APPS = ("uninstall", "unins0", "readme", "read me", "release notes", "help", "manual", "website", "setup", "repair")


@dataclass(frozen=True)
class InstalledApp:
    name: str  # as the Start menu shows it, e.g. "Adobe Photoshop 2025"
    exe: str  # its program's file name, lower case, e.g. "photoshop.exe"


def start_menu_folders() -> list[Path]:
    folders = []
    for variable in ("APPDATA", "PROGRAMDATA"):
        if base := os.environ.get(variable):
            folders.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [folder for folder in folders if folder.is_dir()]


def _shortcut_target_with_com() -> Callable[[Path], str]:
    """A function giving a shortcut's target path, through Windows' own
    shortcut reader (WScript.Shell). Created once, on the calling thread."""
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    return lambda path: shell.CreateShortcut(str(path)).TargetPath


def installed_apps(folders: Iterable[Path] | None = None, target: Callable[[Path], str] | None = None) -> list[InstalledApp]:
    """The Start menu's apps, one per program, by name. Never raises: a
    shortcut that can't be read is skipped."""
    try:
        folders = list(start_menu_folders() if folders is None else folders)
        target = target or _shortcut_target_with_com()
    except Exception:
        log.warning("Could not read the Start menu's apps", exc_info=True)
        return []
    found: dict[str, InstalledApp] = {}
    for folder in folders:
        try:
            shortcuts = sorted(folder.rglob("*.lnk"))
        except OSError:
            continue
        for shortcut in shortcuts:
            name = shortcut.stem
            if any(word in name.lower() for word in NOT_APPS):
                continue
            try:
                path = target(shortcut) or ""
            except Exception:
                log.debug("Could not read the shortcut %s", shortcut.name, exc_info=True)
                continue
            exe = Path(path.replace("\\", "/")).name.lower()
            if not exe.endswith(".exe") or exe == "winlight.exe" or any(word in exe for word in ("unins", "uninstall")):
                continue
            # One entry per program: the shortest name wins ("Photoshop" over "Photoshop (safe mode)").
            if exe not in found or len(name) < len(found[exe].name):
                found[exe] = InstalledApp(name, exe)
    return sorted(found.values(), key=lambda app: app.name.casefold())
