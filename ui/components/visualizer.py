"""Circular assistant visualizer.

The animation reflects an explicit state supplied by the application. It is
not a fake audio meter: the states shown here are the real assistant states
(standby now; listening/thinking/speaking in later phases).
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ui.theme import ACCENT, BLUE, SUCCESS, TEXT_MUTED

_STATE_COLORS = {
    "standby": ACCENT,
    "idle": ACCENT,
    "listening": ACCENT,
    "thinking": BLUE,
    "speaking": SUCCESS,
    "offline": TEXT_MUTED,
    "error": "#f87171",
}
_STATE_SPEEDS = {
    "standby": 0.45,
    "idle": 0.45,
    "listening": 1.35,
    "thinking": 1.8,
    "speaking": 1.1,
    "offline": 0.08,
    "error": 0.2,
}


class AssistantVisualizer(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "standby"
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(210, 210)
        self.setMaximumSize(280, 280)
        self._timer.start()

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state if state in _STATE_COLORS else "standby"
        self.update()

    def state(self) -> str:
        return self._state

    def _tick(self) -> None:
        self._angle = (self._angle + _STATE_SPEEDS.get(self._state, 0.5)) % 360.0
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        painter.scale(side / 260.0, side / 260.0)

        base = QColor(_STATE_COLORS.get(self._state, ACCENT))
        active = self._state not in {"offline", "standby", "idle"}
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * (2.6 if active else 1.2))

        # Outer tick ring.
        tick_pen = QPen(QColor(base.red(), base.green(), base.blue(), 54), 1.0)
        painter.setPen(tick_pen)
        for index in range(72):
            angle = math.radians(index * 5.0)
            inner = 116.0
            outer = 122.0 if index % 6 else 125.0
            painter.drawLine(
                QPointF(math.cos(angle) * inner, math.sin(angle) * inner),
                QPointF(math.cos(angle) * outer, math.sin(angle) * outer),
            )

        # Outer dashed boundary.
        dashed = QPen(QColor(base.red(), base.green(), base.blue(), 38), 1.0)
        dashed.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dashed)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 112.0, 112.0)

        # Rotating arcs.
        conical = QConicalGradient(0.0, 0.0, -self._angle)
        conical.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 10))
        conical.setColorAt(0.35, QColor(base.red(), base.green(), base.blue(), 210))
        conical.setColorAt(0.55, QColor(base.red(), base.green(), base.blue(), 40))
        conical.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 10))
        arc_pen = QPen()
        arc_pen.setBrush(conical)
        arc_pen.setWidthF(2.6)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        for index in range(3):
            radius = 98.0 - index * 8.0
            rect = QRectF(-radius, -radius, radius * 2.0, radius * 2.0)
            start = int((self._angle * 16 + index * 120 * 16) % (360 * 16))
            span = int((52 + index * 12) * 16)
            painter.drawArc(rect, start, span)

        # Counter-rotating inner track.
        inner_pen = QPen(QColor(120, 190, 255, 62), 1.0)
        painter.setPen(inner_pen)
        radius = 72.0
        rect = QRectF(-radius, -radius, radius * 2.0, radius * 2.0)
        painter.drawArc(rect, int((-self._angle * 2 * 16) % (360 * 16)), int(120 * 16))

        # Core glow.
        core_radius = 20.0 + pulse * (5.0 if active else 2.0)
        glow = QRadialGradient(QPointF(0, 0), core_radius * 3.0)
        glow.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 150))
        glow.setColorAt(0.45, QColor(base.red(), base.green(), base.blue(), 38))
        glow.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), core_radius * 3.0, core_radius * 3.0)

        painter.setBrush(QColor(7, 14, 25, 235))
        painter.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 190), 1.4))
        painter.drawEllipse(QPointF(0, 0), 46.0, 46.0)

        font = QFont("Segoe UI")
        font.setPixelSize(30)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(base.red(), base.green(), base.blue(), 235))
        painter.drawText(
            QRectF(-30, -30, 60, 60),
            Qt.AlignmentFlag.AlignCenter,
            "J",
        )

        # Orbiting marker dots.
        painter.setPen(Qt.PenStyle.NoPen)
        for index, opacity in ((0, 190), (1, 120), (2, 70)):
            theta = math.radians(self._angle * (1.0 + index * 0.35) + index * 120.0)
            orbit = 64.0 + index * 17.0
            painter.setBrush(QColor(base.red(), base.green(), base.blue(), opacity))
            painter.drawEllipse(
                QPointF(math.cos(theta) * orbit, math.sin(theta) * orbit),
                1.8 if index else 2.6,
                1.8 if index else 2.6,
            )
