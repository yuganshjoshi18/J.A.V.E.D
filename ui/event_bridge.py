"""Queued bridge from the thread-safe event bus into the Qt main thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.event_manager import Event, EventBus
from utils.logger import get_logger

log = get_logger("ui.events")


class EventBridge(QObject):
    event_received = Signal(object)

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._unsubscribe = bus.subscribe("*", self._relay)

    def _relay(self, event: Event) -> None:
        # Emitting from a worker thread is safe: Qt queues the signal for the
        # bridge's thread (the GUI thread), so slots never touch widgets
        # cross-thread.
        self.event_received.emit(event)

    def close(self) -> None:
        try:
            self._unsubscribe()
        except Exception:
            log.debug("Event bridge already unsubscribed.", exc_info=True)
