# SPDX-License-Identifier: GPL-3.0-only
"""The release scheme and the installer's identity."""

import importlib.util
import pathlib
import re

import pytest

from nightlight import __version__

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The installer's AppId: upgrades, the uninstaller and Windows' Apps list find
# the installed copy by it. Changing it would install a second copy beside
# the first. Never change it.
APP_ID = "{{F658C16C-1589-4566-8E3C-295499D77F23}"


def build_module():
    spec = importlib.util.spec_from_file_location("build", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("version", "numbers"), [
    ("0.3.0-alpha.2", (0, 3, 0, 1002)),
    ("0.3.0-beta.1", (0, 3, 0, 2001)),
    ("0.3.0-beta.12", (0, 3, 0, 2012)),
    ("0.3.0-rc.1", (0, 3, 0, 3001)),
    ("0.3.0", (0, 3, 0, 9000)),
    ("0.3.0-dev", (0, 3, 0, 0)),
    ("0.2.0-beta", (0, 2, 0, 2000)),
])
def test_windows_file_versions(version, numbers):
    assert build_module().numeric(version) == numbers


def test_file_versions_increase_from_beta_to_release():
    numeric = build_module().numeric
    order = ["0.2.0-beta", "0.3.0-alpha.1", "0.3.0-beta.1", "0.3.0-beta.2", "0.3.0-rc.1", "0.3.0", "0.3.1-beta.1"]
    assert [numeric(v) for v in order] == sorted(numeric(v) for v in order)


@pytest.mark.parametrize("version", ["0.3", "v0.3.0", "0.3.0-beta.0", "0.3.0-gamma.1", "0.3.0-dev.2", "0.3.0-beta.1000"])
def test_bad_versions_are_refused(version):
    with pytest.raises(ValueError):
        build_module().numeric(version)


def test_the_app_version_follows_the_scheme():
    build_module().numeric(__version__)


def test_the_installer_app_id_never_changes():
    script = (ROOT / "packaging" / "winlight.iss").read_text(encoding="utf-8")
    assert re.search(r"^AppId=(.+)$", script, re.M).group(1) == APP_ID


def test_the_uninstaller_deletes_the_data_folder_the_app_uses_by_default():
    """An uninstall is a full uninstall unless the user says No: it deletes
    the folder the app keeps its settings in (and its name before 0.3.0),
    only after everything else is removed, and only when asked or silent."""
    from nightlight import config

    script = (ROOT / "packaging" / "winlight.iss").read_text(encoding="utf-8")
    for folder in (config.DATA_FOLDER, config.OLD_DATA_FOLDER):
        assert f"DelTree(ExpandConstant('{{localappdata}}\\{folder}'), True, True, True)" in script
    asked = script.split("function InitializeUninstall(): Boolean;")[1].split("end;\n\nprocedure")[0]
    assert "DeleteSettings := True;" in asked and "if not UninstallSilent then" in asked and "MB_YESNO) = IDYES" in asked
    post = script.split("if CurUninstallStep = usPostUninstall then")[1]
    assert post.index("if DeleteSettings then") < post.index("DelTree(")
    assert script.count("DelTree(") == 2
    # Inno's preprocessor takes a line starting with # as a directive (#13#10 broke the build once).
    directives = {line.split()[0] for line in script.splitlines() if line.lstrip().startswith("#")}
    assert directives <= {"#ifndef", "#error", "#endif"}, directives


def test_the_uninstaller_offers_to_put_windows_color_limit_back_without_pushing_it():
    """Windows' color limit is machine-wide, and f.lux or LightBulb may rely
    on it unlocked: the uninstaller only offers to lock it again (No by
    default), only when it's unlocked, never silently, and removes the same
    value the app sets."""
    from nightlight.hardware import win32

    script = (ROOT / "packaging" / "winlight.iss").read_text(encoding="utf-8")
    assert f"IcmKey = '{win32.GAMMA_RANGE_KEY}';" in script and f"GammaRangeValue = '{win32.GAMMA_RANGE_VALUE}';" in script
    assert f"(Value = {win32.EXPANDED_GAMMA_RANGE})" in script
    asked = script.split("LockColorLimit := False;")[1].split("Result := True;")[0]
    assert "if not UninstallSilent and ColorLimitUnlocked() then" in asked and "MB_YESNO or MB_DEFBUTTON2) = IDYES" in asked
    assert "f.lux" in asked and "LightBulb" in asked  # the disclaimer
    assert "'delete \"HKLM\\' + IcmKey + '\" /v ' + GammaRangeValue + ' /f'" in script and "ShellExec('runas'" in script
    post = script.split("if CurUninstallStep = usPostUninstall then")[1]
    assert "if LockColorLimit then" in post


def test_checksums_are_written_as_sha256sum_reads_them(tmp_path):
    import hashlib

    setup, portable = tmp_path / "Winlight-0.3.0-beta.1-setup.exe", tmp_path / "Winlight-0.3.0-beta.1-portable.zip"
    setup.write_bytes(b"installer")
    portable.write_bytes(b"x" * 3_000_000)  # more than one read block
    out = build_module().write_checksums([portable, setup], tmp_path / "SHA256SUMS.txt")
    lines = out.read_bytes().decode().splitlines(keepends=True)
    assert lines == [
        f"{hashlib.sha256(b'x' * 3_000_000).hexdigest()}  {portable.name}\n",
        f"{hashlib.sha256(b'installer').hexdigest()}  {setup.name}\n",
    ]
    assert b"\r" not in out.read_bytes()  # sha256sum -c on Linux reads it as is
