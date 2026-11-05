# SPDX-License-Identifier: GPL-3.0-only
"""A question in Windows 11's style, as its ContentDialog draws one: a title,
a line or two of text, and the answers along a footer band, side by side and
equally wide, the main one in the accent colour. Replaces QMessageBox for
Settings' questions, which drew the icon, layout and buttons of much older
Windows.

Window-modal and opened, not exec()'d: no nested event loop. Enter chooses
the button with focus, else the main one; Esc closes it, answering nothing
(as Cancel). `clicked` is the button chosen, or None.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from nightlight.ui.settings_parts import ActionButton, is_dark
from nightlight.ui.widgets import blend, set_heading_font

WIDTH = 460


class _Footer(QWidget):
    """The band holding the buttons: the window's own colour, under a hairline."""

    def paintEvent(self, _event) -> None:
        palette = self.palette()
        window, text = palette.color(QPalette.ColorRole.Window), palette.color(QPalette.ColorRole.WindowText)
        painter = QPainter(self)
        painter.fillRect(self.rect(), window)
        painter.setPen(QPen(blend(window, text, 0.12), 0))
        painter.drawLine(0, 0, self.width(), 0)


class Prompt(QDialog):
    def __init__(self, parent: QWidget | None, window_title: str, title: str, message: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAccessibleName(title)
        self.clicked: ActionButton | None = None
        self._default: ActionButton | None = None
        self._buttons: list[ActionButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QVBoxLayout()
        body.setContentsMargins(24, 22, 24, 26)
        body.setSpacing(10)
        self.title = QLabel(title)
        self.title.setWordWrap(True)
        set_heading_font(self.title, 1.3)
        self.message = QLabel(message)
        self.message.setWordWrap(True)
        self.message.setVisible(bool(message))
        body.addWidget(self.title)
        body.addWidget(self.message)
        outer.addLayout(body)
        self._footer = _Footer()
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(24, 20, 24, 20)
        self._footer_layout.setSpacing(8)
        outer.addWidget(self._footer)
        self.setFixedWidth(WIDTH)

    def add_button(self, text: str, kind: str = "standard", default: bool = False) -> ActionButton:
        """A button along the footer, left to right in the order added: the
        main action first, then the others, Cancel last, as Windows orders them."""
        button = ActionButton(text, kind)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(self._on_button)  # bound: a lambda holding self would make a cycle
        self._footer_layout.addWidget(button, 1)
        self._buttons.append(button)
        if default:
            self._default = button
        return button

    def _on_button(self) -> None:
        self.clicked = self.sender()
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFixedHeight(self.sizeHint().height())
        if self._default is not None:
            self._default.setFocus(Qt.FocusReason.OtherFocusReason)  # no ring until the keyboard moves it

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            target = focused if focused in self._buttons else self._default
            if target is not None:
                target.click()
                return
        super().keyPressEvent(event)  # Esc: closed, answering nothing

    def paintEvent(self, _event) -> None:
        # The body a layer lighter than the window, as Windows 11 draws dialogs.
        palette = self.palette()
        window = palette.color(QPalette.ColorRole.Window)
        fill = blend(window, QColor("#ffffff"), 0.06 if is_dark(palette) else 0.7)
        QPainter(self).fillRect(self.rect(), fill)
