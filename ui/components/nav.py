"""Sidebar navigation row with an honest phase badge."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui.theme import repolish


class NavRow(QWidget):
    clicked = Signal(str)

    def __init__(
        self,
        key: str,
        label: str,
        *,
        badge: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.button = QPushButton(label, self)
        self.button.setObjectName("NavButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setCheckable(False)
        self.button.clicked.connect(lambda: self.clicked.emit(self.key))
        layout.addWidget(self.button, 1)

        self.badge = QLabel(badge.upper(), self)
        self.badge.setObjectName("PhaseBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setProperty("phase", badge.upper())
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_active(self, active: bool) -> None:
        self.button.setProperty("active", active)
        self.badge.setProperty("active", active)
        repolish(self.button)
        repolish(self.badge)
