"""Explicit phase-locked page.

Nothing here pretends to work. Each page states its delivery phase, the
foundation that already exists, and what is intentionally absent.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.components.cards import Card, CardHeader, PageHeader, StatusPill, make_button
from ui.theme import repolish


class ComingSoonPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(
        self,
        *,
        title: str,
        phase: int,
        phase_name: str,
        description: str,
        planned: list[str],
        foundation: list[str],
        settings_target: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._phase = phase
        self._phase_name = phase_name
        self.setObjectName("Page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        header = PageHeader(
            title,
            f"Scheduled for Phase {phase} — {phase_name}.",
            eyebrow=f"J.A.V.E.D. // Phase {phase:02d}",
        )
        pill = StatusPill(f"Phase {phase}", "accent")
        header.add_action(pill)
        outer.addWidget(header)

        hero = Card(margins=(26, 24, 26, 24), spacing=14)
        hero_row = QVBoxLayout()
        hero_row.setSpacing(10)
        not_ready = QLabel("NOT YET AVAILABLE")
        not_ready.setObjectName("Eyebrow")
        hero_row.addWidget(not_ready)
        headline = QLabel(f"{title} arrives in Phase {phase}.")
        headline.setObjectName("Display")
        headline.setWordWrap(True)
        hero_row.addWidget(headline)
        copy = QLabel(description)
        copy.setObjectName("BodyCopy")
        copy.setWordWrap(True)
        hero_row.addWidget(copy)

        phase_number = QLabel(f"{phase:02d}")
        phase_number.setObjectName("PhaseGhost")
        phase_number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        hero.body.addWidget(phase_number)
        hero.body.addLayout(hero_row)

        if settings_target:
            action_row = QVBoxLayout()
            action_row.setContentsMargins(0, 8, 0, 0)
            open_settings = make_button("Open Settings", "ghost")
            open_settings.clicked.connect(
                lambda: self.navigate_requested.emit(settings_target)
            )
            row = QWidget()
            from PySide6.QtWidgets import QHBoxLayout

            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(open_settings, 0)
            row_layout.addStretch(1)
            action_row.addWidget(row)
            hero.body.addLayout(action_row)

        outer.addWidget(hero)

        columns = QWidget()
        from PySide6.QtWidgets import QHBoxLayout

        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)

        planned_card = Card()
        planned_card.body.addWidget(
            CardHeader("Planned capabilities", "What this module will provide when delivered.")
        )
        for item in planned:
            bullet = QLabel(f"—  {item}")
            bullet.setObjectName("Bullet")
            bullet.setWordWrap(True)
            planned_card.body.addWidget(bullet)
        planned_card.body.addStretch(1)
        columns_layout.addWidget(planned_card, 1)

        foundation_card = Card()
        foundation_card.body.addWidget(
            CardHeader(
                "Foundation already in place",
                "These facts are read from the running application, not mocked.",
            )
        )
        for item in foundation:
            bullet = QLabel(f"—  {item}")
            bullet.setObjectName("BulletMuted")
            bullet.setWordWrap(True)
            foundation_card.body.addWidget(bullet)
        foundation_card.body.addStretch(1)
        columns_layout.addWidget(foundation_card, 1)

        outer.addWidget(columns, 1)

        footer = QLabel(
            "This page contains no simulated data or decorative controls. "
            "It will be enabled only when the underlying module has been implemented and tested."
        )
        footer.setObjectName("Footnote")
        footer.setWordWrap(True)
        outer.addWidget(footer)
        repolish(self)
