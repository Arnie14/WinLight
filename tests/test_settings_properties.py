# SPDX-License-Identifier: GPL-3.0-only
"""Settings files with anything at all in their fields (hypothesis).

config.load() can't raise: a value no check foresaw sends it to its last
resort, default settings for everything, with the file kept aside as
settings.json.damaged. That keeps Winlight starting, but costs the user
every setting for one bad value. So the property here is stronger than
"loads": one field's bad value costs that field only, and the last resort
is never reached for a file that is a JSON object. Found the first time:
"²" in a cycle shortcut's levels (isdigit() but not int()) reset everything.
"""

import dataclasses
import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nightlight import config
from nightlight.config import BrightnessScheduleConfig, GeneralConfig, NightLightConfig
from nightlight.core.shortcuts import ACTIONS

# Text that looks like numbers: digits of any script (Unicode's Nd, which
# int() reads), and characters that only look like digits (No: "²", "①"),
# in the shapes the fields take: "100, 50, 5" and "23:59". Plain random text
# almost never lands on these, the very ones that tripped int().
# Hypothesis draws the simplest characters first ("0" for Nd), so the traps
# get a weight of their own: superscripts, circled and fraction digits (No),
# Roman numerals (Nl), and digits of other scripts (Nd, which int() reads).
traps = st.sampled_from(["²", "³", "①", "½", "Ⅳ", "٣", "５", "𝟘"])
digit_like = st.sampled_from("0123456789") | traps | st.characters(categories=("No", "Nl")) | st.characters(categories=("Nd",))
numberish = st.lists(digit_like, min_size=1, max_size=3).map("".join)
level_lists = st.lists(numberish, max_size=5).map(", ".join)
times = st.tuples(numberish, numberish).map(":".join)

# Any JSON value, with text from all of Unicode: digits of other scripts,
# "²", combining marks, NUL, astral characters.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(10**30), 10**30) | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=12) | numberish | level_lists | times
    | st.sampled_from(["23:59", "25:99", "Ctrl+Alt+Up", "sunrise", "times"]),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=10,
)


def section(cls):
    """Some of a section's fields, each anything; times where a field takes one."""
    return st.fixed_dictionaries({}, optional={f.name: (times | json_values) if f.name.endswith(("_start", "_time")) else json_values
                                               for f in dataclasses.fields(cls)})


# Real keys and actions: a shortcut whose keys don't parse is dropped before
# its other fields are read, so random ones would never reach them.
shortcut = st.fixed_dictionaries({
    "keys": st.sampled_from(["Ctrl+Alt+Up", "Ctrl+Alt+Home", "Win+Shift+F13"]),
    "action": st.sampled_from(sorted(ACTIONS)),
    "value": json_values | numberish,
    "display": json_values,
    "levels": level_lists | json_values,
})
point = st.fixed_dictionaries({"level": json_values | numberish, "at": times | json_values, "anchor": json_values,
                               "offset_minutes": json_values | numberish})
display = st.fixed_dictionaries(dict.fromkeys(("name", "hidden", "show", "hdr_manual"), json_values))


def every_field(cls):
    """All of a section's fields, each anything; times where a field takes one."""
    return st.fixed_dictionaries({f.name: (times | numberish | json_values) if f.name.endswith(("_start", "_time")) else json_values | numberish
                                  for f in dataclasses.fields(cls)})


# A setting kept valid in every file: if it comes back as the default, the
# whole file was given up on.
SENTINEL = {"general": {"theme": "dark"}}


def loads_without_losing_everything(tmp_path, document: dict) -> None:
    path = tmp_path / "settings.json"
    damaged = path.with_name(path.name + ".damaged")
    damaged.unlink(missing_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = config.load(path)
    assert not damaged.exists(), "a value sent the whole file to default settings"
    general = document.get("general")
    if isinstance(general, dict) and general.get("theme") == "dark":
        assert loaded.general.theme == "dark"
    config.save(loaded, path)
    assert config.load(path) == loaded  # and it settles: nothing drifts with each start


FOCUSED = settings(max_examples=300, suppress_health_check=[HealthCheck.function_scoped_fixture])


@FOCUSED
@given(st.lists(shortcut, min_size=1, max_size=4))
def test_no_shortcut_can_cost_every_setting(tmp_path, shortcuts):
    loads_without_losing_everything(tmp_path, {**SENTINEL, "shortcuts": shortcuts})


@FOCUSED
@given(every_field(NightLightConfig))
def test_no_night_light_setting_can_cost_every_setting(tmp_path, night_light):
    loads_without_losing_everything(tmp_path, {**SENTINEL, "night_light": night_light})


@FOCUSED
@given(every_field(GeneralConfig))
def test_no_general_setting_can_cost_every_setting(tmp_path, general):
    loads_without_losing_everything(tmp_path, {"general": general, "night_light": {"night_temperature": 3100}})


@FOCUSED
@given(every_field(BrightnessScheduleConfig), st.lists(point, max_size=5))
def test_no_brightness_schedule_setting_can_cost_every_setting(tmp_path, fields, points):
    loads_without_losing_everything(tmp_path, {**SENTINEL, "brightness_schedule": {**fields, "points": points}})


@FOCUSED
@given(st.dictionaries(st.text(max_size=10) | numberish, display, min_size=1, max_size=3))
def test_no_display_setting_can_cost_every_setting(tmp_path, displays):
    loads_without_losing_everything(tmp_path, {**SENTINEL, "displays": displays})


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.fixed_dictionaries({}, optional={
    "night_light": every_field(NightLightConfig) | json_values,
    "general": every_field(GeneralConfig) | json_values,
    "brightness_schedule": json_values,
    "shortcuts": st.lists(shortcut | json_values, max_size=4) | json_values,
    "displays": json_values,
    "version": json_values,
}))
def test_no_whole_file_can_cost_every_setting(tmp_path, document):
    loads_without_losing_everything(tmp_path, document)
