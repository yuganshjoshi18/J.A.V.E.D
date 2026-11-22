"""Cards, headers, pills and metric tiles."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import repolish


def make_button(text: str, variant: str = "ghost", parent: QWidget | None = None) -> QPushButton:
    button = QPushButton(text, parent)
    button.setProperty("variant", variant)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(34)
    return button


class Card(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margins: tuple[int, int, int, int] = (18, 16, 18, 16),
        spacing: int = 10,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)


class CardHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        action: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        text_column.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("CardSubtitle")
            self.subtitle_label.setWordWrap(True)
            # A wrapped subtitle should not dictate the card's minimum width.
            self.subtitle_label.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            self.subtitle_label.setMinimumWidth(0)
            text_column.addWidget(self.subtitle_label)
        layout.addLayout(text_column, 1)
        if action is not None:
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignRight)


class PageHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        eyebrow: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        if eyebrow:
            eyebrow_label = QLabel(eyebrow.upper())
            eyebrow_label.setObjectName("Eyebrow")
            column.addWidget(eyebrow_label)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        column.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle")
            subtitle_label.setWordWrap(True)
            column.addWidget(subtitle_label)
        layout.addLayout(column, 1)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        layout.addLayout(self.actions, 0)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class StatusPill(QLabel):
    _TONES = {
        "ok": "ok",
        "success": "ok",
        "warning": "warning",
        "error": "error",
        "critical": "error",
        "accent": "accent",
        "info": "accent",
        "unavailable": "muted",
        "not_configured": "warning",
        "muted": "muted",
    }

    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("StatusPill")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(tone, text)

    def set_status(self, tone: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text.upper())
        self.setProperty("tone", self._TONES.get(tone, "muted"))
        repolish(self)


class StatTile(Card):
    def __init__(self, title: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=(16, 14, 16, 14), spacing=6)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_label = QLabel(title.upper())
        title_label.setObjectName("TileTitle")
        self.body.addWidget(title_label)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(6)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("TileValue")
        value_row.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignBottom)
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("TileUnit")
        value_row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)
        self.body.addLayout(value_row)

        self.bar = QProgressBar()
        self.bar.setObjectName("MetricBar")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setValue(0)
        self.body.addWidget(self.bar)

        self.detail_label = QLabel("Awaiting first sample")
        self.detail_label.setObjectName("TileDetail")
        self.detail_label.setWordWrap(True)
        self.body.addWidget(self.detail_label)

    def set_metric(
        self,
        value: str,
        *,
        detail: str = "",
        percent: float | None = None,
        severity: str = "normal",
    ) -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        if percent is None:
            self.bar.setValue(0)
        else:
            self.bar.setValue(max(0, min(100, round(percent))))
        self.bar.setProperty("severity", severity)
        repolish(self.bar)


class KeyValueRow(QWidget):
    def __init__(
        self,
        key: str,
        value: str,
        *,
        mono: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(16)
        key_label = QLabel(key)
        key_label.setObjectName("KeyLabel")
        key_label.setMinimumWidth(132)
        value_label = QLabel(value)
        value_label.setObjectName("MonoValue" if mono else "ValueLabel")
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value_label.setWordWrap(True)
        layout.addWidget(key_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(value_label, 1)
        self._value_label = value_label

    def setText_value(self, value: str) -> None:  # noqa: N802 - Qt-style setter
        self._value_label.setText(value)


class EmptyState(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("EmptyState")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
