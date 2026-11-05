# SPDX-License-Identifier: GPL-3.0-only
"""Icons drawn in code, so the app looks the same without an icon theme (Windows has none)."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGradient, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTransform

_SIZE = 64  # drawing coordinates
_PIXMAP_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # tray sizes up to taskbar and Alt+Tab

# Winlight's logo, "Dusk screen": a display with the sun setting inside it.
# Night: the sun half down behind the screen's lower edge, in a dusk sky; day:
# high in a pale one. The app's icon (windows, installer, Start menu) is the
# night one; the tray shows whichever is on. At 24 px and below the screen
# fills the square, without its stand, as Fluent icons simplify small sizes.
_LOGO_SIZE = 256  # drawing coordinates
_SMALL = 24  # px and below: the simplified drawing
_INDIGO, _VIOLET, _DEEP = QColor("#2B2A6B"), QColor("#6A46B8"), QColor("#1E1D4A")
_CANDLE, _AMBER, _EMBER = QColor("#FFD98A"), QColor("#FFB23E"), QColor("#FF6F2E")
_SKY_DEEP, _SKY_LIGHT = QColor("#4F8FE8"), QColor("#DCEEFF")
_STAND = QColor("#8C90A8")


def app_icon(night: bool = True) -> QIcon:
    """Winlight's logo: at night (the app's own icon), or by day (the tray while night light is off)."""
    icon = QIcon()
    for size in _PIXMAP_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / _LOGO_SIZE, size / _LOGO_SIZE)
        _draw_logo(painter, night, small=size <= _SMALL)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _vertical(top: QColor, bottom: QColor) -> QLinearGradient:
    """Top to bottom of whatever it fills."""
    gradient = QLinearGradient(0, 0, 0, 1)
    gradient.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
    gradient.setColorAt(0, top)
    gradient.setColorAt(1, bottom)
    return gradient


def _draw_logo(painter: QPainter, night: bool, small: bool) -> None:
    screen = QRectF(12, 34, 232, 168) if small else QRectF(22, 34, 212, 150)
    radius = 30 if small else 26
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_vertical(_INDIGO, _VIOLET) if night else _vertical(_SKY_DEEP, _SKY_LIGHT))
    painter.drawRoundedRect(screen, radius, radius)
    if night:
        # Half a sun on the screen's lower edge, and a glow along the horizon.
        sun_radius = 62 if small else 52
        horizon = screen.bottom() - 2
        sun = QPainterPath(QPointF(128 - sun_radius, horizon))
        sun.arcTo(QRectF(128 - sun_radius, horizon - sun_radius, 2 * sun_radius, 2 * sun_radius), 180, -180)
        sun.closeSubpath()
        painter.setBrush(_vertical(_CANDLE, _EMBER))
        painter.drawPath(sun)
        glow = QColor(_EMBER)
        glow.setAlphaF(0.55)
        painter.setBrush(glow)
        painter.drawRect(QRectF(screen.left() + 18, screen.bottom() - 4, screen.width() - 36, 4))
    else:
        sun_radius = 40 if small else 30
        painter.setBrush(_vertical(_CANDLE, _AMBER))
        painter.drawEllipse(QPointF(128, screen.top() + screen.height() * 0.48), sun_radius, sun_radius)
    if not small:
        painter.setBrush(_STAND)
        painter.drawRect(QRectF(114, screen.bottom(), 28, 22))
        painter.drawRoundedRect(QRectF(76, screen.bottom() + 20, 104, 14), 7, 7)
    # A fine edge, as Fluent icons have: light on the dusk screen, dark on the pale one (on light taskbars).
    edge = QColor("#FFFFFF" if night else _DEEP.name())
    edge.setAlphaF(0.16 if night else 0.28)
    painter.setPen(QPen(edge, 8 if small else 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(screen, radius, radius)


def night_icon() -> QIcon:
    """A crescent moon: night light on, in the panel's Night Light card."""

    def draw(painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f5c26b"))
        painter.drawEllipse(QRectF(6, 6, 52, 52))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(QRectF(22, -2, 48, 48))

    return _icon(draw)


def day_icon() -> QIcon:
    """A sun: night light off, in the panel's Night Light card."""

    def draw(painter: QPainter) -> None:
        color = QColor("#f2a93b")
        pen = QPen(color, 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = QPointF(_SIZE / 2, _SIZE / 2)
        for i in range(8):
            angle = i * math.pi / 4
            direction = QPointF(math.cos(angle), math.sin(angle))
            painter.drawLine(center + direction * 22, center + direction * 29)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, 14, 14)

    return _icon(draw)


def refresh_glyph(color: QColor) -> QIcon:
    """A circular arrow, for "detect monitors again"."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(13, 13, 38, 38), 60 * 16, 290 * 16)
        # Arrowhead at the arc's start (60°), pointing along it.
        tip = QPointF(32 + 19 * math.cos(math.radians(60)), 32 - 19 * math.sin(math.radians(60)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon([tip + QPointF(-9, -9), tip + QPointF(9, 2), tip + QPointF(-6, 11)])

    return _icon(draw)


def gear_glyph(color: QColor) -> QIcon:
    """A cog, for "Configure…"."""

    def draw(painter: QPainter) -> None:
        center = QPointF(_SIZE / 2, _SIZE / 2)
        gear = QPainterPath()
        gear.addEllipse(center, 18, 18)
        for i in range(8):
            tooth = QPainterPath()
            tooth.addRoundedRect(QRectF(-5.5, -27, 11, 12), 2.5, 2.5)
            gear.addPath(QTransform().translate(center.x(), center.y()).rotate(i * 45).map(tooth))
        hole = QPainterPath()
        hole.addEllipse(center, 7.5, 7.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(gear.simplified().subtracted(hole))

    return _icon(draw)


def moon_glyph(color: QColor) -> QIcon:
    """An outlined crescent, for the Night Light page."""

    def draw(painter: QPainter) -> None:
        moon = QPainterPath()
        moon.addEllipse(QRectF(10, 10, 44, 44))
        bite = QPainterPath()
        bite.addEllipse(QRectF(24, 2, 40, 40))
        pen = QPen(color, 5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(moon.subtracted(bite))

    return _icon(draw)


def sun_glyph(color: QColor) -> QIcon:
    """An outlined sun, for the Brightness page."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = QPointF(_SIZE / 2, _SIZE / 2)
        painter.drawEllipse(center, 11, 11)
        for i in range(8):
            angle = i * math.pi / 4
            direction = QPointF(math.cos(angle), math.sin(angle))
            painter.drawLine(center + direction * 19, center + direction * 26)

    return _icon(draw)


def display_glyph(color: QColor) -> QIcon:
    """A monitor on a stand, for the Displays page."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(7, 11, 50, 33), 4, 4)
        painter.drawLine(QPointF(32, 44), QPointF(32, 53))
        painter.drawLine(QPointF(21, 54), QPointF(43, 54))

    return _icon(draw)


def keyboard_glyph(color: QColor) -> QIcon:
    """A keyboard, for the Shortcuts page."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(6, 16, 52, 32), 5, 5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for row, y in enumerate((24, 31)):
            for column in range(5 - row):
                painter.drawRect(QRectF(14 + column * 8 + row * 4, y, 4, 4))
        painter.drawRoundedRect(QRectF(20, 39, 24, 4), 1.5, 1.5)  # the space bar

    return _icon(draw)


def pause_glyph(color: QColor) -> QIcon:
    """Two bars, for "Suspend Night Light"."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(17, 13, 10, 38), 3, 3)
        painter.drawRoundedRect(QRectF(37, 13, 10, 38), 3, 3)

    return _icon(draw)


def play_glyph(color: QColor) -> QIcon:
    """A triangle pointing right, for "Resume Night Light"."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolygon([QPointF(21, 13), QPointF(50, 32), QPointF(21, 51)])

    return _icon(draw)


def power_glyph(color: QColor) -> QIcon:
    """A power symbol, for "Quit"."""

    def draw(painter: QPainter) -> None:
        pen = QPen(color, 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(13, 15, 38, 38), 125 * 16, 290 * 16)  # open at the top
        painter.drawLine(QPointF(32, 9), QPointF(32, 31))

    return _icon(draw)


def report_glyph(color: QColor) -> QIcon:
    """A speech bubble with an exclamation mark, for "Report a Problem…"."""

    def draw(painter: QPainter) -> None:
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(8, 9, 48, 36), 7, 7)
        tail = QPainterPath()
        tail.addPolygon([QPointF(18, 42), QPointF(18, 56), QPointF(32, 42)])
        pen = QPen(color, 5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(bubble.united(tail))
        painter.drawLine(QPointF(32, 18), QPointF(32, 29))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(32, 37), 3.2, 3.2)

    return _icon(draw)


def _icon(draw: Callable[[QPainter], None]) -> QIcon:
    """Draw at each size the tray may ask for (16-32 px depending on DPI)
    rather than letting Windows shrink one large image into a blur."""
    icon = QIcon()
    for size in _PIXMAP_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / _SIZE, size / _SIZE)
        draw(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
