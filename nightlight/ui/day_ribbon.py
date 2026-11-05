# SPDX-License-Identifier: GPL-3.0-only
"""A day of night light at a glance: a strip from midnight to midnight, each
moment painted in the white the screen shows then (the same blackbody table
as the gamma ramps), with a needle at the time shown.

In Settings it follows the settings on the page, applied or not, so changing
the times shows the day changing; the 24-hour preview moves its needle. The
panel shows a slim one under Night Light. The Brightness page shows a day of
its schedule as a small chart instead (BrightnessDay): a level reads as a
height and a number, where a grey didn't.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from nightlight.core.clock import wall_time
from nightlight.ui.widgets import blend, kelvin_color

SAMPLES = 144  # one color per 10 minutes of a 24-hour day: transitions read as gradients
BAR = 22  # px, the full ribbon
SLIM_BAR = 5
HOURS = (0, 6, 12, 18, 24)
REDRAW_MS = 60_000  # the needle moves a pixel or so a minute
NEUTRAL = 6500


def brightness_color(level: float) -> QColor:
    """A brightness level (0 to 100) as a grey: dim to white."""
    return QColor.fromRgbF(*([0.16 + 0.84 * max(0.0, min(1.0, level / 100))] * 3))


def day_bounds(moment: datetime, zone: tzinfo | None) -> tuple[datetime, datetime]:
    """The midnight `moment`'s day starts at and the next one, in `zone`:
    23 or 25 hours apart on a daylight saving change (core/clock.py)."""
    if zone is None:
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    day = moment.astimezone(zone).date()
    return wall_time(day, time(0), zone), wall_time(day + timedelta(days=1), time(0), zone)


class DayRibbon(QWidget):
    def __init__(self, temperature_at: Callable[[datetime], int], now: Callable[[], datetime], slim: bool = False,
                 zone: Callable[[], tzinfo | None] = lambda: None, color_of: Callable[[float], QColor] = kelvin_color,
                 fallback: int = NEUTRAL, name: str = "Night light today") -> None:
        """`temperature_at` gives the value at a moment, painted with
        `color_of`: kelvins by default, or brightness levels with
        brightness_color. `fallback` is painted when it can't be worked out."""
        super().__init__()
        self._temperature_at = temperature_at
        self._color_of = color_of
        self._fallback = fallback
        self._now = now
        self._zone = zone
        self._slim = slim
        self._marker: datetime | None = None  # a moment to show instead of now (the 24-hour preview)
        self._kelvins: list[int] | None = None  # one per sample of _day
        self._day: tuple[date, datetime] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(SLIM_BAR + 2 if slim else BAR + self.fontMetrics().height() + 6)
        self.setToolTip(f"{name}, from midnight to midnight; the line is now")
        self.setAccessibleName(name)
        self._timer = QTimer(self, interval=REDRAW_MS)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def refresh(self) -> None:
        """The settings changed: work the day out again."""
        self._kelvins = None
        self.update()

    def set_marker(self, moment: datetime | None) -> None:
        self._marker = moment
        self.update()

    def kelvins(self, start: datetime, end: datetime) -> list[int]:
        """The temperature at each sample from `start` to `end`, worked out
        once per day and settings."""
        if self._kelvins is None or self._day != (start.date(), start):
            self._day = (start.date(), start)
            step = (end - start) / SAMPLES
            try:
                self._kelvins = [self._temperature_at(start + step * i) for i in range(SAMPLES + 1)]
            except Exception:  # a setting half typed in mustn't stop the window painting
                self._kelvins = [self._fallback] * (SAMPLES + 1)
        return self._kelvins

    def paintEvent(self, _event) -> None:
        if self.width() < 4:
            return
        moment = self._marker or self._now()
        start, end = day_bounds(moment, self._zone())
        span = end - start
        palette = self.palette()
        window, text = palette.color(QPalette.ColorRole.Window), palette.color(QPalette.ColorRole.WindowText)
        dark = window.lightnessF() < 0.5
        bar_height = SLIM_BAR if self._slim else BAR
        bar = QRectF(0.5, 0.5, self.width() - 1, bar_height)
        gradient = QLinearGradient(QPointF(bar.left(), 0), QPointF(bar.right(), 0))
        for i, kelvin in enumerate(self.kelvins(start, end)):
            # Softened toward the window in dark mode, so day isn't a glaring white bar.
            color = self._color_of(kelvin)
            gradient.setColorAt(i / SAMPLES, blend(window, color, 0.78) if dark else color)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(blend(window, text, 0.18), 1))
        painter.setBrush(gradient)
        radius = bar_height / 2 if self._slim else 6
        painter.drawRoundedRect(bar, radius, radius)

        x = bar.left() + bar.width() * max(0.0, min(1.0, (moment - start) / span))
        # The needle, in the text color with a halo of the window's, so it shows on amber and on white.
        for color, width in ((window, 4), (text, 2)):
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, bar.top() + 1.5), QPointF(x, bar.bottom() - 1.5))
        if self._slim:
            return
        painter.setPen(blend(window, text, 0.55))
        font = painter.font()
        font.setPointSizeF(font.pointSizeF() * 0.85)
        painter.setFont(font)
        self._hour_labels(painter, bar, start, end, bar.bottom() + 3)

    def _hour_labels(self, painter: QPainter, bar: QRectF, start: datetime, end: datetime, label_top: float) -> None:
        span = end - start
        zone = self._zone()
        for hour in HOURS:
            label = f"{hour:02d}:00"
            # Where the clock shows that hour: off the even spacing on a daylight saving change.
            at = end if hour == 24 else (start + timedelta(hours=hour) if zone is None else wall_time(start.astimezone(zone).date(),
                                                                                                         time(hour), zone))
            hx = bar.left() + bar.width() * (at - start) / span
            width = painter.fontMetrics().horizontalAdvance(label)
            left = min(max(hx - width / 2, bar.left()), bar.right() - width)  # the ends stay inside
            painter.drawText(QRectF(left, label_top, width + 2, self.height() - label_top), Qt.AlignmentFlag.AlignLeft, label)


CHART = 64  # px, the brightness chart's plot
_ACCENT = getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight)


class BrightnessDay(DayRibbon):
    """A day of the brightness schedule as a small chart: the level from
    midnight to midnight as a line in the accent colour over a light fill,
    faint lines at 25, 50 and 75%, and the needle at now with the level then.

    A strip of greys, as night light's colours are drawn, didn't read: 40%
    and 60% look much alike, and a grey says no number. Night light keeps
    its ribbon, where the colour is the information."""

    def __init__(self, level_at: Callable[[datetime], int], now: Callable[[], datetime],
                 zone: Callable[[], tzinfo | None] = lambda: None, name: str = "Brightness today") -> None:
        super().__init__(level_at, now, zone=zone, color_of=brightness_color, fallback=100, name=name)
        self.setFixedHeight(CHART + self.fontMetrics().height() + 6)
        self.setToolTip(f"{name}, from midnight to midnight: the line is the level, the needle now")

    def level_now(self) -> int:
        """The level at the needle, as the chart labels it."""
        moment = self._marker or self._now()
        start, end = day_bounds(moment, self._zone())
        levels = self.kelvins(start, end)
        index = round(SAMPLES * max(0.0, min(1.0, (moment - start) / (end - start))))
        return int(levels[index])

    def paintEvent(self, _event) -> None:
        if self.width() < 4:
            return
        moment = self._marker or self._now()
        start, end = day_bounds(moment, self._zone())
        palette = self.palette()
        window, text = palette.color(QPalette.ColorRole.Window), palette.color(QPalette.ColorRole.WindowText)
        accent = palette.color(_ACCENT)
        plot = QRectF(0.5, 0.5, self.width() - 1, CHART)
        inner = plot.adjusted(1, 5, -1, -4)  # room for the line's width at 0% and 100%
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(blend(window, text, 0.18), 1))
        painter.setBrush(blend(window, text, 0.03))
        painter.drawRoundedRect(plot, 6, 6)

        def y_of(level: float) -> float:
            return inner.bottom() - inner.height() * max(0.0, min(100.0, level)) / 100

        grid = QPen(blend(window, text, 0.1), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid)
        for level in (25, 50, 75):
            painter.drawLine(QPointF(inner.left() + 4, y_of(level)), QPointF(inner.right() - 4, y_of(level)))

        levels = self.kelvins(start, end)
        points = [QPointF(inner.left() + inner.width() * i / SAMPLES, y_of(level)) for i, level in enumerate(levels)]
        area = QPainterPath(QPointF(points[0].x(), inner.bottom()))
        for point in points:
            area.lineTo(point)
        area.lineTo(QPointF(points[-1].x(), inner.bottom()))
        area.closeSubpath()
        fill = QLinearGradient(QPointF(0, inner.top()), QPointF(0, inner.bottom()))
        top, bottom = QColor(accent), QColor(accent)
        top.setAlphaF(0.32)
        bottom.setAlphaF(0.06)
        fill.setColorAt(0, top)
        fill.setColorAt(1, bottom)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(area)
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        pen = QPen(accent, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)

        # Now: the needle, a dot on the line, and the level then.
        x = inner.left() + inner.width() * max(0.0, min(1.0, (moment - start) / (end - start)))
        level = self.level_now()
        for color, width in ((window, 4), (text, 2)):
            needle = QPen(color, width)
            needle.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(needle)
            painter.drawLine(QPointF(x, plot.top() + 3), QPointF(x, plot.bottom() - 3))
        dot = QPointF(x, y_of(level))
        painter.setPen(QPen(window, 2))
        painter.setBrush(accent)
        painter.drawEllipse(dot, 4.5, 4.5)
        label = f"{level}%"
        font = painter.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width, height = metrics.horizontalAdvance(label) + 10, metrics.height() + 2
        # Beside the dot, on the side with room, above it unless that leaves the chart.
        left = x + 8 if x + 8 + width <= plot.right() - 2 else x - 8 - width
        top_y = dot.y() - height - 2 if dot.y() - height - 2 >= plot.top() + 2 else dot.y() + 4
        tag = QRectF(left, min(top_y, plot.bottom() - height - 2), width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(window)
        painter.drawRoundedRect(tag, 4, 4)
        painter.setPen(text)
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, label)

        painter.setPen(blend(window, text, 0.55))
        font = painter.font()
        font.setWeight(QFont.Weight.Normal)
        font.setPointSizeF(font.pointSizeF() * 0.85)
        painter.setFont(font)
        self._hour_labels(painter, plot, start, end, plot.bottom() + 3)
