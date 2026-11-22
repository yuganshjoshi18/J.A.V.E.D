"""Agent control center placeholder (Phase 7)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.components.coming_soon import ComingSoonPage
from ui.foundation import FOUNDATION_FACTS


class AgentCenterPage(ComingSoonPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent=parent,
            title="Agent Control Center",
            phase=7,
            phase_name="Agent orchestration",
            description=(
                "No agents are running in this build. Phase 7 adds the coordinator, plan "
                "visualisation, approval requests, iterative execution, verification and the "
                "emergency stop control. The event bus, task manager and permission settings "
                "needed by that engine already exist."
            ),
            planned=[
                "Goal intake with explicit plan and risk assessment",
                "Coordinator delegating to specialised agents",
                "Step-by-step progress from real task state",
                "Approval gates at permission levels 2–4",
                "Verification evidence before completion is reported",
                "Emergency stop that cancels tasks and audio",
            ],
            foundation=FOUNDATION_FACTS,
            settings_target="settings",
        )
