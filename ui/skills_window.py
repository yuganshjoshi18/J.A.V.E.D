"""Skills and integrations placeholder (Phase 13)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.components.coming_soon import ComingSoonPage
from ui.foundation import FOUNDATION_FACTS


class SkillsWindowPage(ComingSoonPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent=parent,
            title="Skills & Integrations",
            phase=13,
            phase_name="Extensibility and hardware preparation",
            description=(
                "The skill registry and device integrations are not built. Phase 13 adds a "
                "signed/validated skill manifest system plus documented WebSocket contracts "
                "for the Android companion and ESP32-S3. No untrusted plugin may load silently."
            ),
            planned=[
                "Skill manifest: schema, permissions, risk, timeout, dependencies",
                "Explicit activation, configuration and testing",
                "Android companion API for notifications and communication",
                "ESP32-S3 activation and status protocol",
                "Trust validation before any plugin code executes",
            ],
            foundation=FOUNDATION_FACTS,
            settings_target="settings",
        )
