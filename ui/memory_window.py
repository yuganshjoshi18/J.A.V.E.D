"""Memory manager placeholder (Phase 5)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.components.coming_soon import ComingSoonPage
from ui.foundation import FOUNDATION_FACTS


class MemoryWindowPage(ComingSoonPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent=parent,
            title="Memory Manager",
            phase=5,
            phase_name="Persistent, user-controlled memory",
            description=(
                "The SQLite schema already includes a memory table, but capture, review and "
                "retrieval are not implemented. Phase 5 adds explicit, editable memory with "
                "search, retention, export, import and deletion controls."
            ),
            planned=[
                "Categorised memories: preferences, projects, environment, facts",
                "Propose-then-confirm capture (no silent retention)",
                "Search, edit, delete and export/import",
                "Retention limits and conversation-history controls",
                "Local retrieval; optional semantic index only if justified",
            ],
            foundation=FOUNDATION_FACTS,
            settings_target="settings",
        )
