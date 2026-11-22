"""Lightweight GitHub-flavoured sparkline painted with QPainter."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ui.theme import ACCENT, TEXT_DIM


class Sparkline(QWidget):
    def __init__(
        self,
        *,
        color: str = ACCENT,
        max_points: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._color = QColor(color)
        self._max_points = max(2, max_points)
        self._fixed_max: float | None = None
        self.setMinimumHeight(64)
        self.setMinimumWidth(120)

    def set_max_points(self, count: int) -> None:
        self._max_points = max(2, int(count))
        self._values = self._values[-self._max_points :]
        self.update()

    def set_max_value(self, value: float | None) -> None:
        self._fixed_max = value
        self.update()

    def add_value(self, value: float) -> None:
        self._values.append(float(value))
        self._values = self._values[-self._max_points :]
        self.update()

    def set_values(self, values: list[float]) -> None:
        self._values = [float(value) for value in values[-self._max_points :]]
        self.update()

    def clear(self) -> None:
        self._values.clear()
        self.update()

    def values(self) -> list[float]:
        return list(self._values)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2.0, 5.0, -2.0, -5.0)

        grid_pen = QPen(QColor(255, 255, 255, 16), 1.0)
        painter.setPen(grid_pen)
        for index in range(1, 4):
            y = rect.top() + rect.height() * index / 4.0
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        if len(self._values) < 2:
            painter.setPen(QColor(TEXT_DIM))
            font = QFont("Segoe UI")
            font.setPixelSize(11)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Collecting samples…")
            return

        maximum = self._fixed_max
        if maximum is None:
            maximum = max(max(self._values), 0.001) * 1.2
        maximum = max(maximum, 0.001)

        count = len(self._values)
        step = rect.width() / max(1, count - 1)
        points = [
            QPointF(
                rect.left() + index * step,
                rect.bottom() - (value / maximum) * rect.height(),
            )
            for index, value in enumerate(self._values)
        ]

        line_path = QPainterPath(points[0])
        for point in points[1:]:
            line_path.lineTo(point)

        fill_path = QPainterPath(line_path)
        fill_path.lineTo(QPointF(rect.right(), rect.bottom()))
        fill_path.lineTo(QPointF(rect.left(), rect.bottom()))
        fill_path.closeSubpath()

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top_color = QColor(self._color)
        top_color.setAlpha(64)
        bottom_color = QColor(self._color)
        bottom_color.setAlpha(0)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.fillPath(fill_path, gradient)

        pen = QPen(self._color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line_path)

        last = points[-1]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(last, 2.6, 2.6)
