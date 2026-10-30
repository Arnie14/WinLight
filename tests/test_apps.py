# SPDX-License-Identifier: GPL-3.0-only
"""Picking apps by name for the app lists, from the Start menu's shortcuts."""

import sys

import pytest
from PySide6.QtCore import Qt

from nightlight.system.apps import InstalledApp, installed_apps


def start_menu(tmp_path, shortcuts: dict[str, str]):
    """Fake shortcut files, and a reader giving each one's target."""
    targets = {}
    for relative, target in shortcuts.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        targets[path.name] = target
    return [tmp_path], lambda path: targets[path.name]


def test_apps_are_listed_by_their_start_menu_names_with_their_programs(tmp_path):
    folders, target = start_menu(tmp_path, {
        "Adobe Photoshop 2025.lnk": r"C:\Program Files\Adobe\Photoshop\Photoshop.exe",
        "Video\\VLC media player.lnk": r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        "Video\\Uninstall VLC.lnk": r"C:\Program Files\VideoLAN\VLC\uninstall.exe",  # not an app
        "Docs.lnk": r"C:\Users\x\Documents",  # a folder
        "Our site.lnk": "https://example.com",  # a web page
        "Photoshop (safe mode).lnk": r"C:\Program Files\Adobe\Photoshop\Photoshop.exe",  # the same program
        "Winlight.lnk": r"C:\Users\x\AppData\Local\Programs\Winlight\Winlight.exe",  # itself
    })
    assert installed_apps(folders, target) == [InstalledApp("Adobe Photoshop 2025", "photoshop.exe"),
                                               InstalledApp("VLC media player", "vlc.exe")]


def test_unreadable_shortcuts_and_missing_folders_are_skipped(tmp_path):
    folders, _target = start_menu(tmp_path, {"Good.lnk": r"C:\good.exe", "Broken.lnk": ""})

    def target(path):
        if path.name == "Broken.lnk":
            raise OSError("a damaged shortcut")
        return r"C:\good.exe"

    assert installed_apps([*folders, tmp_path / "missing"], target) == [InstalledApp("Good", "good.exe")]


def test_when_the_start_menu_cant_be_read_at_all_the_list_is_empty(monkeypatch):
    from nightlight.system import apps

    def broken():
        raise OSError("COM unavailable")

    monkeypatch.setattr(apps, "_shortcut_target_with_com", broken)
    assert installed_apps([]) == []


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows' shortcut reader")
def test_the_real_start_menu_reads():
    found = installed_apps()
    assert all(app.exe.endswith(".exe") and app.exe == app.exe.lower() for app in found)


def test_the_picker_searches_and_adds_the_chosen_programs():
    from nightlight.ui.settings_widgets import AppList

    apps = [InstalledApp("Adobe Photoshop 2025", "photoshop.exe"), InstalledApp("DaVinci Resolve", "resolve.exe"),
            InstalledApp("VLC media player", "vlc.exe")]
    app_list = AppList(lambda: ["teams.exe"], installed=lambda: apps)
    app_list.set_apps(("vlc.exe",))
    app_list._fill_menu()
    labels = [action.text() for action in app_list._menu.actions()]
    assert labels[0] == "Choose from installed apps…" and "teams.exe" in labels and labels[-1] == "Browse for a program file…"
    app_list._choose_installed()
    picker = app_list._picker
    shown = [picker.list.item(i).text() for i in range(picker.list.count())]
    assert shown == ["Adobe Photoshop 2025", "DaVinci Resolve"]  # vlc.exe is in the list already
    picker.search.setText("resolve")
    visible = [picker.list.item(i).text() for i in range(picker.list.count()) if not picker.list.item(i).isHidden()]
    assert visible == ["DaVinci Resolve"]
    picker.search.setText("photo")  # the program's name is searched too
    item = next(picker.list.item(i) for i in range(picker.list.count()) if not picker.list.item(i).isHidden())
    item.setSelected(True)
    picker.add_button.click()
    assert app_list.apps() == ("photoshop.exe", "vlc.exe") and app_list._picker is None


def test_the_picker_says_when_the_start_menu_has_nothing():
    from nightlight.ui.settings_widgets import AppList

    app_list = AppList(list, installed=list)
    app_list._choose_installed()
    picker = app_list._picker
    assert picker.list.count() == 1 and not picker.list.isEnabled() and picker.chosen() == []
    picker.reject()
    assert Qt.WindowModality.WindowModal == picker.windowModality()
