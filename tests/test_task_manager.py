from __future__ import annotations

import asyncio
import threading
import time

from core.event_manager import EventBus
from core.task_manager import ManagedTaskStatus, TaskManager


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before the timeout")


def test_task_completes_and_emits_lifecycle(async_runtime) -> None:
    bus = EventBus()
    manager = TaskManager(async_runtime.loop, bus)
    events: list[str] = []
    bus.subscribe("task.created", lambda event: events.append("created"))
    bus.subscribe("task.started", lambda event: events.append("started"))
    bus.subscribe("task.finished", lambda event: events.append("finished"))

    async def work() -> str:
        return "result-value"

    task_id = manager.start("unit-work", work, metadata={"scope": "test"})
    wait_for(lambda: (manager.get(task_id) or {}).get("status") == "completed")

    record = manager.get(task_id)
    assert record is not None
    assert record["result"] == "result-value"
    assert record["metadata"] == {"scope": "test"}
    assert record["started_at"] and record["finished_at"]
    assert events == ["created", "started", "finished"]


def test_task_failure_is_recorded(async_runtime) -> None:
    manager = TaskManager(async_runtime.loop, EventBus())

    async def fail() -> None:
        raise ValueError("expected failure")

    task_id = manager.start("failing", fail)
    wait_for(lambda: (manager.get(task_id) or {}).get("status") == "failed")

    record = manager.get(task_id)
    assert record is not None
    assert "ValueError: expected failure" in (record["error"] or "")


def test_task_timeout(async_runtime) -> None:
    manager = TaskManager(async_runtime.loop, EventBus())

    async def slow() -> None:
        await asyncio.sleep(10)

    task_id = manager.start("slow", slow, timeout=0.1)
    wait_for(lambda: (manager.get(task_id) or {}).get("status") == "timed_out")

    record = manager.get(task_id)
    assert record is not None
    assert "timeout" in (record["error"] or "").lower()


def test_task_cancellation(async_runtime) -> None:
    manager = TaskManager(async_runtime.loop, EventBus())
    entered = threading.Event()

    async def long_running() -> None:
        entered.set()
        await asyncio.sleep(10)

    task_id = manager.start("cancellable", long_running)
    assert entered.wait(timeout=5.0)
    assert manager.cancel(task_id) is True
    wait_for(lambda: (manager.get(task_id) or {}).get("status") == "cancelled")

    assert manager.cancel(task_id) is False


def test_cancel_all_and_prune(async_runtime) -> None:
    manager = TaskManager(async_runtime.loop, EventBus())
    entered = threading.Event()

    async def long_running() -> None:
        entered.set()
        await asyncio.sleep(10)

    first = manager.start("long-1", long_running)
    assert entered.wait(timeout=5.0)
    second = manager.start("long-2", long_running)
    assert manager.cancel_all() == 2
    wait_for(
        lambda: all(
            (manager.get(task_id) or {}).get("status") == "cancelled"
            for task_id in (first, second)
        )
    )

    async def quick() -> str:
        return "done"

    ids = [manager.start("quick", quick) for _ in range(3)]
    wait_for(lambda: all((manager.get(task_id) or {}).get("status") == "completed" for task_id in ids))

    removed = manager.prune_finished(keep=1)
    assert removed == 4
    remaining = manager.snapshot()
    assert len(remaining) == 1
    assert remaining[0]["name"] == "quick"
    assert remaining[0]["status"] == "completed"


def test_start_rejects_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    manager = TaskManager(loop, EventBus())

    async def work() -> None:
        return None

    try:
        manager.start("closed", work)
    except RuntimeError as exc:
        assert "closed" in str(exc).lower()
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError")

    coroutine = work()
    coroutine.close()
