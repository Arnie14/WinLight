# SPDX-License-Identifier: GPL-3.0-only
"""Whether Winlight runs from an MSIX package (the Microsoft Store build),
and where other programs see the files it writes then.

Everything that differs in the package goes behind is_packaged(), so the
installer and portable builds never change (docs/plans/msix-package.md).

A packaged app's writes under %LOCALAPPDATA% and %APPDATA% are redirected
by Windows to the package's own folder, %LOCALAPPDATA%\\Packages\\<family
name>\\LocalCache\\Local (and \\Roaming), which Windows removes with the
package. The app's own file calls see the usual paths; Explorer, Notepad
and a terminal don't. So every path shown to the user or handed to another
program goes through visible_path(). A file that was there before the
package was installed (the installer build's) stays where it is until the
package writes to it, so the redirected path is used only if it exists.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path, PureWindowsPath

log = logging.getLogger(__name__)

APPMODEL_ERROR_NO_PACKAGE = 15700
ERROR_INSUFFICIENT_BUFFER = 122
_UNKNOWN = object()
_family: object = _UNKNOWN  # the package family name, None when not packaged; asked once


def package_family_name() -> str | None:
    """The package's family name ("Winlight_8wekyb3d8bbwe"), or None when
    not running from a package (or on another system)."""
    global _family
    if _family is _UNKNOWN:
        _family = _ask_family_name()
        if _family is not None:
            log.info("Running from an MSIX package (%s)", _family)
    return _family  # type: ignore[return-value]


def is_packaged() -> bool:
    return package_family_name() is not None


def _ask_family_name() -> str | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        get = kernel32.GetCurrentPackageFamilyName
    except AttributeError:  # older than Windows 8: never packaged
        return None
    get.argtypes = [ctypes.POINTER(ctypes.c_uint32), wintypes.LPWSTR]
    get.restype = wintypes.LONG
    length = ctypes.c_uint32(0)
    result = get(ctypes.byref(length), None)
    if result == APPMODEL_ERROR_NO_PACKAGE or result != ERROR_INSUFFICIENT_BUFFER or not length.value:
        return None
    name = ctypes.create_unicode_buffer(length.value)
    if get(ctypes.byref(length), name) != 0:
        return None
    return name.value or None


def visible_path(path: Path) -> Path:
    """Where other programs find `path`, a file or folder the app wrote: the
    package's redirected copy when packaged and there is one, else `path`."""
    family = package_family_name()
    if family is None:
        return path
    for variable, kind in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming")):
        base = os.environ.get(variable)
        if not base:
            continue
        relative = _relative_to(path, Path(base))
        if relative is None or (relative.parts and relative.parts[0].lower() == "packages"):
            continue  # not under it, or already the package's own folder
        redirected = Path(os.environ.get("LOCALAPPDATA", base)) / "Packages" / family / "LocalCache" / kind / relative
        return redirected if redirected.exists() else path
    return path


def _relative_to(path: Path, base: Path) -> Path | None:
    """`path` relative to `base`, comparing as Windows does (any case, either slash)."""
    child, parent = PureWindowsPath(str(path)), PureWindowsPath(str(base))
    child_parts, parent_parts = [p.lower() for p in child.parts], [p.lower() for p in parent.parts]
    if child_parts[:len(parent_parts)] != parent_parts:
        return None
    return Path(*child.parts[len(parent_parts):]) if len(child.parts) > len(parent_parts) else Path()
