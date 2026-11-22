"""Audit trail service: durable local record of consequential actions."""

from __future__ import annotations

from typing import Any

from core.event_manager import EventBus, safe_event_detail
from memory.repositories import AuditRepository
from utils.logger import get_logger

log = get_logger("audit")


class AuditService:
    def __init__(self, repository: AuditRepository, bus: EventBus) -> None:
        self._repository = repository
        self._bus = bus

    def record(
        self,
        category: str,
        action: str,
        *,
        detail: Any = "",
        actor: str = "system",
        success: bool = True,
        announce: bool = True,
    ) -> None:
        text = safe_event_detail(detail)
        try:
            entry_id = self._repository.record(
                category,
                action,
                detail=text,
                actor=actor,
                success=success,
            )
        except Exception:
            log.exception("Audit write failed for %s/%s.", category, action)
            return
        log.info("Audit %s/%s (id=%s, success=%s)", category, action, entry_id, success)
        if announce:
            self._bus.emit(
                "audit.recorded",
                source="audit",
                entry={
                    "id": entry_id,
                    "category": category,
                    "action": action,
                    "detail": text,
                    "actor": actor,
                    "success": success,
                },
            )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "category": item.category,
                "action": item.action,
                "detail": item.detail,
                "actor": item.actor,
                "success": item.success,
            }
            for item in self._repository.recent(limit)
        ]
