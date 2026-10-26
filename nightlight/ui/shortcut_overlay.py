# SPDX-License-Identifier: GPL-3.0-only
"""What a shortcut just did, on screen for a moment: each display's new
brightness, or night light's state, near the bottom of the screen above the
taskbar (where Twinkle Tray shows its overlay).

The lessons from Twinkle Tray's issues: it never takes focus (#479: typing
stopped in the app in front), lets clicks through, and isn't shown over an
exclusive-fullscreen game or presentation (#83: such a game was minimized);
the app decides that. Same window style as the preview note, which is
checked on the test laptop (WS_EX_NOACTIVATE, WS_EX_TRANSPARENT).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication, QPainter, QPalette, QPen
from PySide6.QtWidgets import QWidget

from nightlight.ui.settings_parts import accent
from nightlight.ui.widgets import blend

SHOW_MS = 2200
WIDTH = 300
PADDING = 16
ROW = 40  # a display: its name and level, and a bar
ABOVE_TASKBAR = 56
RADIUS = 8.0
MAX_ROWS = 6


class ShortcutOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        for attribute in (Qt.WidgetAttribute.WA_ShowWithoutActivating, Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          Qt.WidgetAttribute.WA_TranslucentBackground):
            self.setAttribute(attribute)
        self._levels: list[tuple[str, int]] = []
        self._message = ""
        self._timer = QTimer(self, singleShot=True, interval=SHOW_MS)
        self._timer.timeout.connect(self.hide)

    def show_levels(self, levels: list[tuple[str, int]]) -> None:
        """(display name, level) for each display changed."""
        self._levels, self._message = levels[:MAX_ROWS], ""
        self._show(PADDING * 2 + ROW * len(self._levels) - 8)

    def show_message(self, text: str) -> None:
        self._levels, self._message = [], text
        self._show(PADDING * 2 + QFontMetrics(self.font()).height() + 4)

    def _show(self, height: int) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.setGeometry(area.center().x() - WIDTH // 2, area.bottom() - height - ABOVE_TASKBAR, WIDTH, height)
        self.update()
        self.show()
        self._timer.start()  # each use keeps it up a moment longer

    def paintEvent(self, _event) -> None:
        palette = self.palette()
        window, text = palette.color(QPalette.ColorRole.Window), palette.color(QPalette.ColorRole.WindowText)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(blend(window, text, 0.18), 1))
        painter.setBrush(window)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        inner = QRectF(self.rect()).adjusted(PADDING, PADDING, -PADDING, -PADDING)
        metrics = painter.fontMetrics()
        painter.setPen(text)
        if self._message:
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, metrics.elidedText(self._message, Qt.TextElideMode.ElideRight,
                                                                                     int(inner.width())))
            return
        fill, track = accent(palette), blend(window, text, 0.18)
        for i, (name, level) in enumerate(self._levels):
            top = inner.top() + i * ROW
            value = f"{level}%"
            value_width = metrics.horizontalAdvance(value)
            painter.setPen(text)
            painter.drawText(QRectF(inner.left(), top, inner.width() - value_width - 8, metrics.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(name, Qt.TextElideMode.ElideRight, int(inner.width() - value_width - 8)))
            painter.drawText(QRectF(inner.right() - value_width, top, value_width, metrics.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
            bar = QRectF(inner.left(), top + metrics.height() + 6, inner.width(), 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, 2, 2)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0, min(100, level)) / 100, bar.height()), 2, 2)
