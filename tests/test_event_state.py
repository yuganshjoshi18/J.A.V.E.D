from __future__ import annotations

import threading

import pytest

from core.event_manager import EventBus, safe_event_detail
from core.state_manager import AppStatus, StateManager


def test_subscription_wildcard_and_unsubscribe() -> None:
    bus = EventBus()
    received: list[tuple[str, dict]] = []

    unsubscribe = bus.subscribe("*", lambda event: received.append((event.type, event.payload)))
    bus.emit("one", value=1)
    bus.emit("two", value=2)

    assert [item[0] for item in received] == ["one", "two"]
    unsubscribe()
    unsubscribe()  # idempotent
    bus.emit("three", value=3)
    assert len(received) == 2
    assert bus.subscriber_count() == 0


def test_handler_failure_does_not_block_other_handlers() -> None:
    bus = EventBus()
    received: list[str] = []

    def broken(event) -> None:
        raise RuntimeError("boom")

    bus.subscribe("event", broken)
    bus.subscribe("event", lambda event: received.append(event.get("value")))

    event = bus.emit("event", value="ok")

    assert received == ["ok"]
    assert event.type == "event"


def test_async_handler_runs_on_provided_loop(async_runtime) -> None:
    bus = EventBus(loop_provider=lambda: async_runtime.loop)
    finished = threading.Event()
    seen: list[str] = []

    async def handler(event) -> None:
        seen.append(event.get("value"))
        finished.set()

    bus.subscribe("async.event", handler)
    bus.emit("async.event", value="handled")

    assert finished.wait(timeout=5.0)
    assert seen == ["handled"]


def test_async_handler_without_loop_is_dropped() -> None:
    bus = EventBus()
    called = False

    async def handler(event) -> None:
        nonlocal called
        called = True

    bus.subscribe("dropped", handler)
    bus.emit("dropped")

    assert called is False


def test_safe_event_detail_redacts_and_truncates() -> None:
    detail = safe_event_detail({"api_key": "AIza" + "x" * 30, "note": "AIza" + "y" * 30}, limit=40)

    assert "AIza" + "x" * 30 not in detail
    assert "[REDACTED]" in detail
    assert len(detail) <= 40


def test_state_manager_transitions_and_emits_changes() -> None:
    bus = EventBus()
    state = StateManager(bus)
    events: list[dict] = []
    bus.subscribe("state.changed", lambda event: events.append(event.payload))

    ready = state.transition(AppStatus.READY, "online")

    assert ready.status == "ready"
    assert state.snapshot.status == "ready"
    assert len(events) == 1
    assert events[0]["changed"] == {"status": "ready", "detail": "online"}

    state.update(status="ready")  # unchanged fields are not announced
    assert len(events) == 1

    state.set_error("broken")
    assert state.snapshot.status == "degraded"
    assert state.snapshot.last_error == "broken"

    with pytest.raises(KeyError, match="Unknown state fields"):
        state.update(nonsense=True)
