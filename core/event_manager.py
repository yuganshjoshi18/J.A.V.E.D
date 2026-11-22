"""Thread-safe event bus with async-handler support.

Services publish immutable events; the Qt layer subscribes through a bridge
that converts emissions into queued Qt signals, so no widget is ever touched
from a worker thread.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger, redact_text
from utils.time import utc_now_iso

log = get_logger("events")

EventHandler = Callable[["Event"], Any]


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)
    source: str = "core"

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


class EventBus:
    def __init__(self, loop_provider: Callable[[], asyncio.AbstractEventLoop] | None = None) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = threading.RLock()
        self._loop_provider = loop_provider

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        """Subscribe to an event type, or ``*`` for every event.

        Returns an idempotent unsubscribe callable.
        """
        if not event_type:
            raise ValueError("event_type must not be empty.")
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subscribers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def subscriber_count(self, event_type: str | None = None) -> int:
        with self._lock:
            if event_type is None:
                return sum(len(handlers) for handlers in self._subscribers.values())
            return len(self._subscribers.get(event_type, []))

    def emit(self, event_type: str, *, source: str = "core", **payload: Any) -> Event:
        event = Event(type=event_type, payload=payload, source=source)
        with self._lock:
            handlers = list(self._subscribers.get(event_type, []))
            if event_type != "*":
                handlers.extend(self._subscribers.get("*", []))
        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    self._schedule(result)
            except Exception:
                log.exception("Event handler failed for '%s'.", event_type)
        return event

    def _schedule(self, awaitable: Any) -> None:
        loop = self._loop_provider() if self._loop_provider else None
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(awaitable, loop)
            return
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        log.warning("Async event handler dropped: event loop is not running.")


def safe_event_detail(value: Any, limit: int = 2000) -> str:
    """Serialise event/audit detail without secrets and with a hard size cap."""
    if isinstance(value, str):
        text = value
    else:
        import json

        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    return redact_text(text)[:limit]
