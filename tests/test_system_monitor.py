from __future__ import annotations

import asyncio

import pytest

from core.event_manager import EventBus
from core.services.system_monitor import SystemMetricsCollector, SystemMonitorService


def test_collector_returns_real_host_metrics() -> None:
    collector = SystemMetricsCollector(top_process_count=5)

    metrics = collector.collect()

    assert metrics["timestamp"]
    assert 0.0 <= metrics["cpu"]["percent"] <= 100.0
    assert (metrics["cpu"]["count"] or 0) >= 1
    assert metrics["memory"]["total"] > 0
    assert 0.0 <= metrics["memory"]["percent"] <= 100.0
    assert isinstance(metrics["disks"], list)
    assert isinstance(metrics["processes"], list)
    assert len(metrics["processes"]) <= 5
    assert all({"pid", "name", "cpu_percent", "memory_percent"} <= set(row) for row in metrics["processes"])
    assert isinstance(metrics["warnings"], list)
    assert "network" in metrics and "up" in metrics["network"]


def test_top_process_count_is_clamped() -> None:
    collector = SystemMetricsCollector(top_process_count=999)
    assert len(collector.collect()["processes"]) <= 20

    collector.set_top_process_count(0)
    assert len(collector.collect()["processes"]) <= 3


def test_monitor_service_publishes_samples_and_stops() -> None:
    class FakeCollector:
        def __init__(self) -> None:
            self.calls = 0

        def collect(self) -> dict:
            self.calls += 1
            return {"timestamp": "now", "cpu": {"percent": 1.0}, "calls": self.calls}

    async def scenario() -> None:
        bus = EventBus()
        service = SystemMonitorService(FakeCollector(), bus, 0.5)
        received: list[dict] = []
        seen = asyncio.Event()

        def handler(event) -> None:
            received.append(event.get("metrics"))
            seen.set()

        bus.subscribe("system.metrics", handler)
        task = asyncio.create_task(service.run())
        await asyncio.wait_for(seen.wait(), timeout=5.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert received
        assert received[0]["cpu"]["percent"] == 1.0

    asyncio.run(scenario())


def test_interval_is_clamped() -> None:
    service = SystemMonitorService(SystemMetricsCollector(), EventBus(), 0.01)
    assert service._interval == 0.5
    service.set_interval(999)
    assert service._interval == 30.0
