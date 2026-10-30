# SPDX-License-Identifier: GPL-3.0-only
"""The cycle and refresh shortcuts, and "Add the usual"."""

import json

import pytest

from nightlight import config
from nightlight.config import GeneralConfig
from nightlight.core.shortcuts import (
    BRIGHTNESS_CYCLE,
    BRIGHTNESS_UP,
    PANEL,
    REFRESH,
    Shortcut,
    cycle_levels,
    next_in_cycle,
)
from tests.test_app import start  # noqa: F401  (a fixture)
from tests.test_shortcuts import DELL, PANEL_MONITOR, TV, harness

CYCLE = Shortcut("Ctrl+Alt+Home", BRIGHTNESS_CYCLE, levels="100, 50, 1")


@pytest.mark.parametrize(("text", "levels"), [
    ("100, 50, 1", (100, 50, 1)),
    ("100 50 1", (100, 50, 1)),
    ("100;50%;1", (100, 50, 1)),
    ("100, 100, 50, 50, 1", (100, 50, 1)),  # a level right after itself once
    ("150, -5, x, 30", (100, 30)),  # over 100 is 100; what isn't a level (-5, x) is left out
    ("", ()),
    (",".join(["10", "20"] * 10), (10, 20, 10, 20, 10, 20, 10, 20, 10, 20)),  # at most ten
])
def test_cycle_levels_are_read_forgivingly(text, levels):
    assert cycle_levels(text) == levels


@pytest.mark.parametrize(("current", "minimum", "expected"), [
    (100, 0, 50), (50, 0, 1), (1, 0, 100),  # through the list, and round again
    (73, 0, 100),  # set by hand in between: starts again from the first
    (None, 0, 100),  # not known yet
    (20, 20, 100),  # a TV that can't go below 20: its 1 is 20, and from there the list goes round
])
def test_the_next_level_follows_the_current_one(current, minimum, expected):
    assert next_in_cycle((100, 50, 1), current, minimum) == expected


def test_a_cycle_needs_two_levels_and_switches_have_no_display():
    assert Shortcut("Ctrl+Alt+Home", BRIGHTNESS_CYCLE, levels="50").normalized() is None
    assert Shortcut("Ctrl+Alt+Home", BRIGHTNESS_CYCLE, levels="50, 50").normalized() is None
    assert CYCLE.normalized() == CYCLE
    assert Shortcut("Ctrl+Alt+P", PANEL, display="DEL41A2", levels="1, 2").normalized() == Shortcut("Ctrl+Alt+P", PANEL)


def test_cycle_and_refresh_shortcuts_are_saved_and_loaded(tmp_path):
    path = tmp_path / "settings.json"
    shortcuts = (CYCLE, Shortcut("Ctrl+Alt+R", REFRESH))
    config.save(config.AppConfig(shortcuts=shortcuts), path)
    assert config.load(path).shortcuts == shortcuts
    path.write_text(json.dumps({"shortcuts": [{"keys": "Ctrl+Alt+Home", "action": "brightness_cycle", "levels": 5}]}))
    assert config.load(path).shortcuts == ()  # levels that aren't text: not a cycle, dropped


def test_each_display_cycles_from_its_own_level():
    run, monitors, shown = harness({"DEL41A2": 100, "BOE0812": 73, "SAM7136": 50}, monitors=(DELL, PANEL_MONITOR, TV))
    run(CYCLE)
    assert monitors.levels == {"DEL41A2": 50, "BOE0812": 100, "SAM7136": 20}  # the TV's 1 is its minimum, 20
    run(CYCLE)
    assert monitors.levels == {"DEL41A2": 1, "BOE0812": 50, "SAM7136": 100}
    assert shown[-1] == [("DELL U2720Q", 1), ("Built-in display", 50), ("Living room TV", 100)]


def test_a_cycle_for_one_display_leaves_the_others():
    run, monitors, _shown = harness({"DEL41A2": 100, "BOE0812": 100}, monitors=(DELL, PANEL_MONITOR))
    run(Shortcut("Ctrl+Alt+Home", BRIGHTNESS_CYCLE, display="BOE0812", levels="100, 30"))
    assert monitors.sent == [("BOE0812", 30)]


def test_refresh_detects_the_displays_again_as_the_command_line_does(start, monkeypatch):  # noqa: F811
    from nightlight import app as app_module

    monkeypatch.setattr(app_module.winsystem, "exclusive_fullscreen", lambda: False)
    night_light, _ = start(GeneralConfig())
    retried = []
    monkeypatch.setattr(night_light.monitors, "retry", lambda: retried.append(True))
    night_light._run_shortcut(Shortcut("Ctrl+Alt+R", REFRESH))
    assert retried == [True]
    assert night_light._shortcut_overlay._message == "Detecting displays again"
    night_light._shortcut_overlay.hide()


# --- The editor --------------------------------------------------------------------------------


def test_the_levels_field_shows_for_a_cycle_only_and_its_hint_says_what_to_type():
    from nightlight.ui.shortcut_editor import NO_CYCLE, ShortcutEditor

    editor = ShortcutEditor()
    editor.set_shortcuts((CYCLE, Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP)))
    cycle, step = editor.rows
    assert not cycle.levels.isHidden() and cycle.value.isHidden() and not cycle.display.isHidden()
    assert step.levels.isHidden()
    assert editor.shortcuts()[0] == CYCLE
    cycle.levels.setText("40")
    editor.show_status(lambda keys: "", ())
    assert cycle.status.text() == NO_CYCLE and editor.shortcuts() == (Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP),)
    cycle.action.setCurrentIndex(cycle.action.findData(REFRESH))
    assert cycle.levels.isHidden() and cycle.display.isHidden()
    assert editor.shortcuts()[0] == Shortcut("Ctrl+Alt+Home", REFRESH)


def test_add_the_usual_adds_what_isnt_there_once_and_then_goes():
    from nightlight.ui.shortcut_editor import USUAL, ShortcutEditor

    editor = ShortcutEditor()
    editor.set_shortcuts((Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 5),))  # one of the two, set up already
    assert not editor.add_usual.isHidden()
    editor.add_usual.click()
    assert editor.shortcuts() == (Shortcut("Ctrl+Alt+Up", BRIGHTNESS_UP, 5), USUAL[1])  # the existing one kept as it was
    assert editor.add_usual.isHidden()
    editor.rows[1].remove.click()
    assert not editor.add_usual.isHidden()
