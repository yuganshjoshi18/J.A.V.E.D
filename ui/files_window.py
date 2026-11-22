"""Files and documents placeholder (Phase 6)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.components.coming_soon import ComingSoonPage
from ui.foundation import FOUNDATION_FACTS


class FilesWindowPage(ComingSoonPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent=parent,
            title="Files & Documents",
            phase=6,
            phase_name="Safe tools and Windows automation",
            description=(
                "No files are read, edited or launched by this build. Phase 6 adds an "
                "allowlisted tool layer restricted to the workspaces you authorise, with "
                "operation logs, confirmation for writes and no unrestricted shell access."
            ),
            planned=[
                "Workspace-confined search, read, create and edit operations",
                "Document drafting and summarisation",
                "Launch approved applications, folders and websites",
                "Every operation logged with a permission decision",
                "Timeouts, cancellation and destructive-action confirmation",
            ],
            foundation=FOUNDATION_FACTS,
            settings_target="settings",
        )
