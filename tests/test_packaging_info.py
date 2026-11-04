# SPDX-License-Identifier: GPL-3.0-only
"""Knowing whether Winlight runs from an MSIX package, and showing the
paths other programs can open then (system/packaging_info.py)."""

import ctypes
import sys
from pathlib import Path

import pytest

from nightlight.system import packaging_info

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")
FAMILY = "Winlight_8wekyb3d8bbwe"


@pytest.fixture(autouse=True)
def ask_afresh(monkeypatch):
    monkeypatch.setattr(packaging_info, "_family", packaging_info._UNKNOWN)


@windows_only
def test_the_installer_build_and_the_tests_are_not_packaged():
    assert packaging_info.package_family_name() is None and not packaging_info.is_packaged()


@windows_only
def test_a_package_is_recognised_by_the_family_name_windows_gives(monkeypatch):
    """The real call path, with kernel32's answer faked as a package would get it:
    first the size (ERROR_INSUFFICIENT_BUFFER), then the name."""

    class Get:
        argtypes = restype = None

        def __call__(self, length, buffer):
            length._obj.value = len(FAMILY) + 1
            if buffer is None:
                return packaging_info.ERROR_INSUFFICIENT_BUFFER
            ctypes.memmove(buffer, ctypes.create_unicode_buffer(FAMILY), (len(FAMILY) + 1) * ctypes.sizeof(ctypes.c_wchar))
            return 0

    class Kernel32:
        GetCurrentPackageFamilyName = Get()

    monkeypatch.setattr(packaging_info.ctypes, "WinDLL", lambda *args, **kwargs: Kernel32())
    assert packaging_info.package_family_name() == FAMILY and packaging_info.is_packaged()


def packaged(monkeypatch, tmp_path):
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(packaging_info, "_family", FAMILY)
    return local, roaming


def test_not_packaged_every_path_is_shown_as_it_is(monkeypatch, tmp_path):
    monkeypatch.setattr(packaging_info, "_family", None)
    assert packaging_info.visible_path(tmp_path / "WinLight" / "Logs") == tmp_path / "WinLight" / "Logs"


def test_packaged_a_file_the_app_wrote_is_shown_where_windows_put_it(monkeypatch, tmp_path):
    local, _roaming = packaged(monkeypatch, tmp_path)
    redirected = local / "Packages" / FAMILY / "LocalCache" / "Local" / "WinLight" / "Reports" / "report.zip"
    redirected.parent.mkdir(parents=True)
    redirected.write_bytes(b"zip")
    assert packaging_info.visible_path(local / "WinLight" / "Reports" / "report.zip") == redirected
    assert packaging_info.visible_path(local / "WinLight" / "Reports") == redirected.parent  # folders too


def test_packaged_a_file_from_before_the_package_stays_where_it_is(monkeypatch, tmp_path):
    """The installer build's files: read in place until the package writes them."""
    local, _roaming = packaged(monkeypatch, tmp_path)
    assert packaging_info.visible_path(local / "WinLight" / "settings.json") == local / "WinLight" / "settings.json"


def test_packaged_roaming_app_data_goes_to_its_own_folder(monkeypatch, tmp_path):
    local, roaming = packaged(monkeypatch, tmp_path)
    redirected = local / "Packages" / FAMILY / "LocalCache" / "Roaming" / "WinLight" / "x.json"
    redirected.parent.mkdir(parents=True)
    redirected.write_text("{}")
    assert packaging_info.visible_path(roaming / "WinLight" / "x.json") == redirected


def test_packaged_paths_elsewhere_and_the_packages_own_folder_are_left_alone(monkeypatch, tmp_path):
    local, _roaming = packaged(monkeypatch, tmp_path)
    elsewhere = tmp_path / "Documents" / "report.txt"
    own = local / "Packages" / FAMILY / "LocalCache" / "Local" / "WinLight"
    own.mkdir(parents=True)
    assert packaging_info.visible_path(elsewhere) == elsewhere
    assert packaging_info.visible_path(own) == own


@windows_only
def test_paths_compare_as_windows_does(monkeypatch, tmp_path):
    local, _roaming = packaged(monkeypatch, tmp_path)
    redirected = local / "Packages" / FAMILY / "LocalCache" / "Local" / "WinLight" / "Logs"
    redirected.mkdir(parents=True)
    other_case = Path(str(local).upper().replace("\\", "/")) / "winlight" / "logs"
    assert packaging_info.visible_path(other_case) == local / "Packages" / FAMILY / "LocalCache" / "Local" / "winlight" / "logs"
