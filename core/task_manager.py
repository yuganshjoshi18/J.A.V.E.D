"""Managed background work with status tracking, timeouts and cancellation.

Used by long-lived services and, in later phases, by the autonomous agent
loop. Every task has a stable id and an inspectable state snapshot that the GUI
can display without guessing.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from core.event_manager import EventBus
from utils.logger import get_logger
from utils.time import utc_now_iso

log = get_logger("tasks")


class ManagedTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class _TaskRecord:
    id: str
    name: str
    status: ManagedTaskStatus = ManagedTaskStatus.PENDING
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: str | None = None
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    asyncio_task: asyncio.Task | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
        }


class TaskManager:
    """Starts coroutines on the runtime loop from any thread."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        bus: EventBus,
        *,
        max_concurrent: int = 8,
    ) -> None:
        self._loop = loop
        self._bus = bus
        self._lock = threading.RLock()
        self._records: dict[str, _TaskRecord] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def start(
        self,
        name: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        timeout: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Schedule a coroutine and return its tracking id immediately."""
        task_id = f"mtk_{uuid.uuid4().hex[:10]}"
        record = _TaskRecord(
            id=task_id,
            name=name,
            timeout_seconds=timeout,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[task_id] = record
        if self._loop.is_closed():
            with self._lock:
                record.status = ManagedTaskStatus.FAILED
                record.error = "Event loop is closed."
                record.finished_at = utc_now_iso()
            raise RuntimeError("Cannot start background task: event loop is closed.")
        self._bus.emit(
            "task.created",
            source="task_manager",
            task=record.snapshot(),
        )
        try:
            self._loop.call_soon_threadsafe(self._create, task_id, coro_factory)
        except RuntimeError as exc:
            with self._lock:
                record.status = ManagedTaskStatus.FAILED
                record.error = str(exc)
                record.finished_at = utc_now_iso()
            raise RuntimeError("Cannot schedule background task.") from exc
        return task_id

    def _create(
        self,
        task_id: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or record.cancel_requested:
                if record is not None:
                    record.status = ManagedTaskStatus.CANCELLED
                    record.finished_at = utc_now_iso()
                return
        try:
            async_task = self._loop.create_task(
                self._run(record, coro_factory),
                name=f"javed:{record.name}",
            )
        except Exception as exc:  # pragma: no cover - loop-level failure
            self._finish(record, ManagedTaskStatus.FAILED, error=str(exc))
            return
        with self._lock:
            record.asyncio_task = async_task

    async def _run(
        self,
        record: _TaskRecord,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:
        async with self._semaphore:
            with self._lock:
                record.status = ManagedTaskStatus.RUNNING
                record.started_at = utc_now_iso()
            self._bus.emit("task.started", source="task_manager", task=record.snapshot())
            try:
                if record.timeout_seconds:
                    async with asyncio.timeout(record.timeout_seconds):
                        result = await coro_factory()
                else:
                    result = await coro_factory()
            except asyncio.CancelledError:
                self._finish(record, ManagedTaskStatus.CANCELLED)
                return
            except TimeoutError:
                self._finish(
                    record,
                    ManagedTaskStatus.TIMED_OUT,
                    error=f"Exceeded {record.timeout_seconds:.0f}s timeout.",
                )
                return
            except Exception as exc:
                log.exception("Background task '%s' failed.", record.name)
                self._finish(record, ManagedTaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
                return
            rendered = None if result is None else str(result)[:500]
            self._finish(record, ManagedTaskStatus.COMPLETED, result=rendered)

    def _finish(
        self,
        record: _TaskRecord,
        status: ManagedTaskStatus,
        *,
        error: str | None = None,
        result: str | None = None,
    ) -> None:
        with self._lock:
            record.status = status
            record.error = error
            record.result = result
            record.finished_at = utc_now_iso()
            snapshot = record.snapshot()
        self._bus.emit("task.finished", source="task_manager", task=snapshot)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or record.status in {
                ManagedTaskStatus.COMPLETED,
                ManagedTaskStatus.FAILED,
                ManagedTaskStatus.CANCELLED,
                ManagedTaskStatus.TIMED_OUT,
            }:
                return False
            record.cancel_requested = True
            async_task = record.asyncio_task
        self._loop.call_soon_threadsafe(self._cancel_on_loop, record, async_task)
        return True

    def _cancel_on_loop(self, record: _TaskRecord, async_task: asyncio.Task | None) -> None:
        if async_task is None:
            with self._lock:
                if record.status == ManagedTaskStatus.PENDING:
                    record.status = ManagedTaskStatus.CANCELLED
                    record.finished_at = utc_now_iso()
                    snapshot = record.snapshot()
                else:
                    snapshot = None
            if snapshot:
                self._bus.emit("task.finished", source="task_manager", task=snapshot)
            return
        async_task.cancel()

    def cancel_all(self) -> int:
        with self._lock:
            ids = [
                task_id
                for task_id, record in self._records.items()
                if record.status
                in {
                    ManagedTaskStatus.PENDING,
                    ManagedTaskStatus.RUNNING,
                }
            ]
        for task_id in ids:
            self.cancel(task_id)
        return len(ids)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(task_id)
            return record.snapshot() if record else None

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.snapshot() for record in self._records.values()]

    def prune_finished(self, keep: int = 50) -> int:
        """Drop old finished records while keeping the newest ``keep`` entries.

        ``finished_at`` has second precision, so insertion order is used as a
        deterministic tie-breaker for records that finish in the same second.
        """
        with self._lock:
            finished = [
                (index, record)
                for index, record in enumerate(self._records.values())
                if record.status
                not in {ManagedTaskStatus.PENDING, ManagedTaskStatus.RUNNING}
            ]
            finished.sort(key=lambda item: (item[1].finished_at or "", item[0]))
            remove = finished[: max(0, len(finished) - max(0, keep))]
            for _, record in remove:
                self._records.pop(record.id, None)
            return len(remove)
