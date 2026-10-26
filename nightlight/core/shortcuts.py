# SPDX-License-Identifier: GPL-3.0-only
"""Keyboard shortcuts: which key combinations can be used, how they are
written ("Ctrl+Alt+Up"), and their Windows codes for RegisterHotKey.

Windows' RegisterHotKey takes modifiers (Ctrl, Alt, Shift, Win) and one
key; anything else held is ignored, so a "combination" of two ordinary keys
fires on the second alone (Twinkle Tray issue #162). Which keys may stand
alone follows LightBulb's HotKeyTextBox: a character key needs Ctrl, Alt or
Win (Shift alone would stop it being typed), Enter, Space and Tab need a
modifier, and function and navigation keys may be used alone, F13 to F24
among them, which keyboard software can send for keys Windows never sees
(Fn, many laptops' brightness keys). Pure logic, no Windows calls.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

# Modifier names, in the order they are written, and their RegisterHotKey flags.
MODIFIERS = {"Ctrl": 0x0002, "Alt": 0x0001, "Shift": 0x0004, "Win": 0x0008}
MOD_NOREPEAT = 0x4000  # held down, the shortcut fires once (for switches, not for steps)

# Key names and their virtual-key codes.
KEYS: dict[str, int] = {
    **{letter: ord(letter) for letter in string.ascii_uppercase},
    **{digit: ord(digit) for digit in string.digits},
    **{f"F{n}": 0x6F + n for n in range(1, 25)},  # F1 = 0x70 ... F24 = 0x87
    **{f"Num{n}": 0x60 + n for n in range(10)},
    "NumMultiply": 0x6A, "NumAdd": 0x6B, "NumSubtract": 0x6D, "NumDecimal": 0x6E, "NumDivide": 0x6F,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22, "Insert": 0x2D, "Delete": 0x2E,
    "Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Backspace": 0x08,
    "Semicolon": 0xBA, "Equals": 0xBB, "Comma": 0xBC, "Minus": 0xBD, "Period": 0xBE, "Slash": 0xBF,
    "Backquote": 0xC0, "BracketLeft": 0xDB, "Backslash": 0xDC, "BracketRight": 0xDD, "Quote": 0xDE,
}
VK_NAMES = {code: name for name, code in KEYS.items()}
# Keys that type a character: usable only with Ctrl, Alt or Win.
CHARACTER_KEYS = frozenset([*string.ascii_uppercase, *string.digits, *(f"Num{n}" for n in range(10)),
                            "NumMultiply", "NumAdd", "NumSubtract", "NumDecimal", "NumDivide",
                            "Semicolon", "Equals", "Comma", "Minus", "Period", "Slash", "Backquote",
                            "BracketLeft", "Backslash", "BracketRight", "Quote"])
NEED_MODIFIER = CHARACTER_KEYS | {"Space", "Enter", "Tab", "Backspace", "Delete"}

# What a shortcut can do. Steps and levels take a value (a percentage).
BRIGHTNESS_UP, BRIGHTNESS_DOWN, BRIGHTNESS_SET = "brightness_up", "brightness_down", "brightness_set"
NIGHT_LIGHT, SUSPEND, PANEL = "night_light", "suspend", "panel"
ACTIONS = (BRIGHTNESS_UP, BRIGHTNESS_DOWN, BRIGHTNESS_SET, NIGHT_LIGHT, SUSPEND, PANEL)
WITH_VALUE = frozenset({BRIGHTNESS_UP, BRIGHTNESS_DOWN, BRIGHTNESS_SET})
# Held down, these repeat (each repeat is another step); the rest fire once.
REPEATING = frozenset({BRIGHTNESS_UP, BRIGHTNESS_DOWN})


@dataclass(frozen=True)
class Chord:
    modifiers: frozenset[str]
    key: str

    def __str__(self) -> str:
        return "+".join([*(m for m in MODIFIERS if m in self.modifiers), self.key])

    @property
    def codes(self) -> tuple[int, int]:
        """(modifier flags, virtual-key code) for RegisterHotKey."""
        flags = 0
        for name in self.modifiers:
            flags |= MODIFIERS[name]
        return flags, KEYS[self.key]


def parse(text: str) -> Chord:
    """"Ctrl+Alt+Up" -> Chord; raises ValueError for anything that isn't
    modifiers and one known key. Case and spaces don't matter."""
    names = {name.lower(): name for name in (*MODIFIERS, *KEYS)}
    parts = [part.strip() for part in text.split("+")]
    if not text.strip() or any(not part for part in parts):
        raise ValueError(f"not a shortcut: {text!r}")
    canonical = []
    for part in parts:
        name = names.get(part.lower())
        if name is None:
            raise ValueError(f"unknown key {part!r} in {text!r}")
        canonical.append(name)
    *modifiers, key = canonical
    if key in MODIFIERS or any(m not in MODIFIERS for m in modifiers) or len(set(modifiers)) != len(modifiers):
        raise ValueError(f"a shortcut is modifiers and one key: {text!r}")
    return Chord(frozenset(modifiers), key)


def problem(chord: Chord) -> str:
    """Why this combination can't be a shortcut, or "" if it can."""
    if chord.key in NEED_MODIFIER and not chord.modifiers - {"Shift"}:
        return "Add Ctrl, Alt or Win: on its own (or with Shift) this key is for typing"
    if chord.key == "F12" and not chord.modifiers:  # RegisterHotKey's documentation
        return "Windows keeps F12 on its own for debuggers: add Ctrl, Alt, Shift or Win"
    return ""


@dataclass(frozen=True)
class Shortcut:
    """A key combination and what it does. `display` is a display key, or ""
    for every display (hidden ones are never changed)."""

    keys: str = ""
    action: str = BRIGHTNESS_UP
    value: int = 10
    display: str = ""

    def normalized(self) -> Shortcut | None:
        """The shortcut as saved, or None if it can't be one (dropped on load)."""
        try:
            chord = parse(self.keys)
        except ValueError:
            return None
        if problem(chord) or self.action not in ACTIONS:
            return None
        low = 0 if self.action == BRIGHTNESS_SET else 1
        return Shortcut(str(chord), self.action, max(low, min(100, int(self.value))), self.display)
