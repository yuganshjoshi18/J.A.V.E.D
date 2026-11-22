"""Research center placeholder (Phase 9)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.components.coming_soon import ComingSoonPage
from ui.foundation import FOUNDATION_FACTS


class ResearchWindowPage(ComingSoonPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent=parent,
            title="Research Center",
            phase=9,
            phase_name="Research and multimodal",
            description=(
                "Web research is not configured. Phase 9 adds a search integration with "
                "source tracking, cross-checking, saved reports and multimodal document "
                "analysis with explicit local/cloud indicators."
            ),
            planned=[
                "Cited multi-source research with verifiable URLs",
                "Saved, reopenable reports under the private data directory",
                "Fact-checking and disagreement reporting",
                "Image, screenshot, PDF and document analysis",
                "Clear cloud-upload consent before private content leaves the device",
            ],
            foundation=FOUNDATION_FACTS,
            settings_target="settings",
        )
