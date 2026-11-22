"""Single source of truth for application-level state shown in the UI."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from config.settings import APP_VERSION, CURRENT_PHASE
from core.event_manager import EventBus
from utils.logger import get_logger
from utils.time import utc_now_iso

log = get_logger("state")


class AppStatus(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


@dataclass(frozen=True)
class AppSnapshot:
    status: str = AppStatus.STARTING.value
    detail: str = "Initialising foundation services"
    started_at: str = ""
    last_error: str | None = None
    listening: bool = False
    memory_enabled: bool = True
    phase: int = CURRENT_PHASE
    version: str = APP_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StateManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._snapshot = AppSnapshot(
            started_at=utc_now_iso(),
            memory_enabled=True,
        )

    @property
    def snapshot(self) -> AppSnapshot:
        with self._lock:
            return self._snapshot

    def update(self, **fields: Any) -> AppSnapshot:
        allowed = set(AppSnapshot.__dataclass_fields__)
        unknown = set(fields) - allowed
        if unknown:
            raise KeyError(f"Unknown state fields: {sorted(unknown)}")
        with self._lock:
            previous = self._snapshot
            self._snapshot = AppSnapshot(**{**previous.to_dict(), **fields})
            updated = self._snapshot
        changed = {
            key: value
            for key, value in fields.items()
            if getattr(previous, key) != value
        }
        if changed:
            self._bus.emit(
                "state.changed",
                source="state",
                state=updated.to_dict(),
                changed=changed,
            )
        return updated

    def transition(self, status: AppStatus, detail: str = "") -> AppSnapshot:
        log.info("State → %s%s", status.value, f" ({detail})" if detail else "")
        return self.update(status=status.value, detail=detail)

    def set_error(self, message: str) -> AppSnapshot:
        return self.update(last_error=message, status=AppStatus.DEGRADED.value)

    def clear_error(self) -> AppSnapshot:
        return self.update(last_error=None)
