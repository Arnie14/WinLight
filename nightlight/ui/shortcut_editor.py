# SPDX-License-Identifier: GPL-3.0-only
"""Editing keyboard shortcuts: one row per shortcut, as in Twinkle Tray's
Hotkeys page: the keys (pressed into a recording field), what they do, how
much, on which display, and whether Windows registered them."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget

from nightlight.core.shortcuts import (
    ACTIONS,
    BRIGHTNESS_DOWN,
    BRIGHTNESS_SET,
    BRIGHTNESS_UP,
    NIGHT_LIGHT,
    PANEL,
    SUSPEND,
    VK_NAMES,
    WITH_VALUE,
    Chord,
    Shortcut,
    caution,
    parse,
    problem,
)
from nightlight.system.shortcuts import DUPLICATE, WORKS
from nightlight.ui.settings_parts import Card, SettingRow
from nightlight.ui.widgets import SecondaryLabel

ACTION_LABELS = {
    BRIGHTNESS_UP: "Brighter by",
    BRIGHTNESS_DOWN: "Dimmer by",
    BRIGHTNESS_SET: "Set brightness to",
    NIGHT_LIGHT: "Turn night light on or off",
    SUSPEND: "Suspend or resume night light",
    PANEL: "Open the panel",
}
ALL_DISPLAYS = ""
MAX_ROWS = 32
NOT_APPLIED = "Click Apply to use it"
NO_KEYS = "Click the field and press the keys"

# Qt's keys, for where Windows' virtual-key code isn't given (tests, other platforms).
_QT_KEYS = {
    **{getattr(Qt.Key, f"Key_{c}"): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    **{getattr(Qt.Key, f"Key_F{n}"): f"F{n}" for n in range(1, 25)},
    Qt.Key.Key_Left: "Left", Qt.Key.Key_Up: "Up", Qt.Key.Key_Right: "Right", Qt.Key.Key_Down: "Down",
    Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown",
    Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete", Qt.Key.Key_Space: "Space", Qt.Key.Key_Return: "Enter",
    Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab", Qt.Key.Key_Backspace: "Backspace",
    Qt.Key.Key_Semicolon: "Semicolon", Qt.Key.Key_Equal: "Equals", Qt.Key.Key_Comma: "Comma", Qt.Key.Key_Minus: "Minus",
    Qt.Key.Key_Period: "Period", Qt.Key.Key_Slash: "Slash", Qt.Key.Key_QuoteLeft: "Backquote",
    Qt.Key.Key_BracketLeft: "BracketLeft", Qt.Key.Key_Backslash: "Backslash", Qt.Key.Key_BracketRight: "BracketRight",
    Qt.Key.Key_Apostrophe: "Quote",
}
_KEYPAD = {**{getattr(Qt.Key, f"Key_{n}"): f"Num{n}" for n in range(10)}, Qt.Key.Key_Asterisk: "NumMultiply",
           Qt.Key.Key_Plus: "NumAdd", Qt.Key.Key_Minus: "NumSubtract", Qt.Key.Key_Period: "NumDecimal",
           Qt.Key.Key_Slash: "NumDivide"}
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_Super_L,
                  Qt.Key.Key_Super_R}
_CLEAR_KEYS = {Qt.Key.Key_Escape, Qt.Key.Key_Backspace, Qt.Key.Key_Delete}


def key_name(event: QKeyEvent) -> str:
    """The key pressed, by this module's names; "" if it can't be a shortcut key."""
    if name := VK_NAMES.get(event.nativeVirtualKey()):
        return name
    if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and event.key() in _KEYPAD:
        return _KEYPAD[event.key()]
    return _QT_KEYS.get(event.key(), "")


def modifier_names(modifiers: Qt.KeyboardModifier) -> frozenset[str]:
    flags = {"Ctrl": Qt.KeyboardModifier.ControlModifier, "Alt": Qt.KeyboardModifier.AltModifier,
             "Shift": Qt.KeyboardModifier.ShiftModifier, "Win": Qt.KeyboardModifier.MetaModifier}
    return frozenset(name for name, flag in flags.items() if modifiers & flag)


class KeyRecorder(QLineEdit):
    """A field that takes a key combination instead of text, with LightBulb's
    rules (HotKeyTextBox): Esc, Backspace or Delete on their own clear it,
    modifiers alone wait for a key, and keys that type need Ctrl, Alt or Win.
    While it has focus, `recording` is True: the app lets go of its own
    shortcuts, so their keys arrive here."""

    keysChanged = Signal(str)
    recordingChanged = Signal(bool)
    refused = Signal(str)  # why the keys just pressed can't be a shortcut

    def __init__(self, keys: str = "") -> None:
        super().__init__(keys)
        self.setReadOnly(True)
        self.setPlaceholderText("Press keys")
        self.setToolTip("Click, then press the key combination. Esc clears it")
        self.setFixedWidth(170)
        self.setAccessibleName("Shortcut keys")

    def event(self, event) -> bool:
        # Every key comes here first, as in QKeySequenceEdit: otherwise a
        # button's Alt+letter or a window's shortcut takes the keys being recorded.
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        # Tab and Shift+Tab would move the focus away instead of being recorded.
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        event.accept()
        if event.key() in _MODIFIER_KEYS or event.isAutoRepeat():
            return
        modifiers = modifier_names(event.modifiers())
        if event.key() in _CLEAR_KEYS and not modifiers:
            self._set("")
            return
        name = key_name(event)
        if not name:
            self.refused.emit("That key can't be used for a shortcut")
            return
        chord = Chord(modifiers, name)
        if reason := problem(chord):
            self.refused.emit(reason)
            return
        self._set(str(chord))

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.recordingChanged.emit(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.recordingChanged.emit(False)

    def _set(self, keys: str) -> None:
        if keys != self.text():
            self.setText(keys)
            self.keysChanged.emit(keys)


class ShortcutRow(QWidget):
    changed = Signal()
    removeRequested = Signal(object)

    def __init__(self, shortcut: Shortcut, displays: list[tuple[str, str]]) -> None:
        super().__init__()
        self.keys = KeyRecorder(shortcut.keys)
        self.action = QComboBox()
        for action in ACTIONS:
            self.action.addItem(ACTION_LABELS[action], action)
        self.action.setCurrentIndex(max(0, self.action.findData(shortcut.action)))
        self.value = QSpinBox(minimum=0, maximum=100, singleStep=5, suffix="%")
        self.value.setValue(shortcut.value)
        self.value.setFixedWidth(84)
        self.display = QComboBox()
        # The lists narrow with the window rather than pushing the row past it.
        for combo, letters in ((self.action, 16), (self.display, 12)):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(letters)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_displays(displays, shortcut.display)
        self.remove = QToolButton(text="✕", toolTip="Remove this shortcut", autoRaise=True)
        # A bound method, not a lambda holding self: that cycle left the widget to
        # the garbage collector, and PySide then deleted it twice (a crash).
        self.remove.clicked.connect(self._request_removal)
        self.status = SecondaryLabel(scale=0.9)
        self.status.setWordWrap(True)

        # Two lines, so a row fits the page at any window size: the keys and
        # how they stand, then what they do.
        keys_line = QHBoxLayout()
        keys_line.setSpacing(10)
        keys_line.addWidget(self.keys)
        keys_line.addWidget(self.status, 1)
        keys_line.addWidget(self.remove)
        action_line = QHBoxLayout()
        action_line.setSpacing(8)
        action_line.addWidget(self.action, 3)
        action_line.addWidget(self.value)
        action_line.addWidget(self.display, 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(keys_line)
        layout.addLayout(action_line)

        self.keys.keysChanged.connect(self._on_changed)
        self.keys.refused.connect(self.status.setText)
        self.action.currentIndexChanged.connect(self._on_changed)
        self.value.valueChanged.connect(self._on_changed)
        self.display.currentIndexChanged.connect(self._on_changed)
        self._sync()

    def set_displays(self, displays: list[tuple[str, str]], selected: str | None = None) -> None:
        """Every display (key, name), keeping the one chosen, also if it isn't connected now."""
        selected = self.display.currentData() if selected is None else selected
        self.display.blockSignals(True)
        self.display.clear()
        self.display.addItem("All displays", ALL_DISPLAYS)
        for key, name in displays:
            self.display.addItem(name, key)
        if selected and self.display.findData(selected) < 0:
            self.display.addItem(f"{selected} (not connected)", selected)
        self.display.setCurrentIndex(max(0, self.display.findData(selected or ALL_DISPLAYS)))
        self.display.blockSignals(False)

    def shortcut(self) -> Shortcut | None:
        """The row as a shortcut; None while it has no keys yet."""
        if not self.keys.text():
            return None
        action = self.action.currentData()
        value = self.value.value() if action in WITH_VALUE else 10
        display = self.display.currentData() if action in WITH_VALUE else ALL_DISPLAYS
        return Shortcut(self.keys.text(), action, value, display).normalized()

    def _sync(self) -> None:
        action = self.action.currentData()
        self.value.setVisible(action in WITH_VALUE)
        self.display.setVisible(action in WITH_VALUE)
        self.value.setMinimum(0 if action == BRIGHTNESS_SET else 1)

    def _on_changed(self, *_args) -> None:
        self._sync()
        self.changed.emit()

    def _request_removal(self) -> None:
        self.removeRequested.emit(self)


class ShortcutEditor(Card):
    """The card of shortcuts, with Add."""

    changed = Signal()
    recordingChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._displays: list[tuple[str, str]] = []
        self.rows: list[ShortcutRow] = []
        self.add_button = QPushButton("Add shortcut")
        self.add_button.clicked.connect(self._add_new)  # bound, as the rows' ✕
        holder = QWidget()
        self._rows_layout = QVBoxLayout(holder)
        self._rows_layout.setContentsMargins(0, 2, 0, 0)
        self._rows_layout.setSpacing(16)
        self.add(SettingRow("Keyboard shortcuts", "Work in any app. A shortcut changes the displays the way the panel "
                            "does; hidden displays are left alone", self.add_button, below=holder))

    def set_shortcuts(self, shortcuts: tuple[Shortcut, ...]) -> None:
        for row in self.rows:
            row.deleteLater()
        self.rows = []
        for shortcut in shortcuts:
            self._add(shortcut)

    def shortcuts(self) -> tuple[Shortcut, ...]:
        return tuple(shortcut for row in self.rows if (shortcut := row.shortcut()) is not None)

    def set_displays(self, displays: list[tuple[str, str]]) -> None:
        self._displays = displays
        for row in self.rows:
            row.set_displays(displays)

    def show_status(self, status_of, saved: tuple[Shortcut, ...]) -> None:
        """Each row's state: Windows' answer for a saved shortcut, else a hint."""
        seen: set[str] = set()
        for row in self.rows:
            shortcut = row.shortcut()
            if shortcut is None:
                text = NO_KEYS
            elif shortcut.keys in seen:
                text = DUPLICATE  # only the first with these keys is registered
            elif shortcut not in saved:
                text = NOT_APPLIED
            else:
                text = status_of(shortcut.keys) or NOT_APPLIED
            if shortcut is not None:
                seen.add(shortcut.keys)
                if text in (WORKS, NOT_APPLIED) and (warning := caution(parse(shortcut.keys))):
                    text = f"{text}. {warning}"
            row.status.setText(text)

    def _add_new(self) -> None:
        self._add(Shortcut(), focus=True)

    def _add(self, shortcut: Shortcut, focus: bool = False) -> None:
        if len(self.rows) >= MAX_ROWS:
            return
        row = ShortcutRow(shortcut, self._displays)
        row.changed.connect(self.changed)
        row.removeRequested.connect(self._remove)
        row.keys.recordingChanged.connect(self.recordingChanged)
        self._rows_layout.addWidget(row)
        self.rows.append(row)
        self.add_button.setEnabled(len(self.rows) < MAX_ROWS)
        if focus:
            row.keys.setFocus(Qt.FocusReason.OtherFocusReason)
        self.changed.emit()

    def _remove(self, row: ShortcutRow) -> None:
        if row.keys.hasFocus():
            self.recordingChanged.emit(False)  # its focus-out may not come: it is going away
        self.rows.remove(row)
        row.hide()
        row.deleteLater()
        self.add_button.setEnabled(True)
        self.changed.emit()
