"""Real Windows system telemetry via psutil.

Nothing in this module fabricates values: every field comes from the host or is
``None`` when Windows does not expose it.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any

import psutil

from utils.logger import get_logger
from utils.time import utc_now_iso

log = get_logger("system_monitor")


class SystemMetricsCollector:
    def __init__(self, *, top_process_count: int = 6) -> None:
        self._top_process_count = max(3, min(int(top_process_count), 20))
        self._lock = RLock()
        self._last_net: tuple[float, int, int] | None = None
        self._last_cpu_wall = time.monotonic()

    def set_top_process_count(self, count: int) -> None:
        with self._lock:
            self._top_process_count = max(3, min(int(count), 20))

    def _network(self) -> dict[str, Any]:
        counters = psutil.net_io_counters()
        now = time.monotonic()
        rate_sent = 0.0
        rate_recv = 0.0
        if counters is not None:
            with self._lock:
                previous = self._last_net
                self._last_net = (now, counters.bytes_sent, counters.bytes_recv)
            if previous is not None:
                elapsed = max(now - previous[0], 0.001)
                rate_sent = max(0.0, (counters.bytes_sent - previous[1]) / elapsed)
                rate_recv = max(0.0, (counters.bytes_recv - previous[2]) / elapsed)
        up = False
        try:
            up = any(stat.isup for stat in psutil.net_if_stats().values())
        except Exception:
            up = False
        return {
            "bytes_sent": counters.bytes_sent if counters else None,
            "bytes_recv": counters.bytes_recv if counters else None,
            "rate_sent": rate_sent,
            "rate_recv": rate_recv,
            "up": up,
        }

    def _disks(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            partitions = psutil.disk_partitions(all=False)
        except Exception:
            return rows
        for partition in partitions:
            if "cdrom" in partition.opts or not partition.fstype:
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except OSError:
                continue
            rows.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "percent": round(float(usage.percent), 1),
                    "used": usage.used,
                    "total": usage.total,
                    "free": usage.free,
                }
            )
            if len(rows) >= 8:
                break
        return rows

    def _top_processes(self) -> list[dict[str, Any]]:
        with self._lock:
            limit = self._top_process_count
        rows: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = process.info
                rows.append(
                    {
                        "pid": int(info.get("pid") or 0),
                        "name": str(info.get("name") or "unknown"),
                        "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                        "memory_percent": round(float(info.get("memory_percent") or 0.0), 1),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        rows.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
        return rows[:limit]

    def collect(self) -> dict[str, Any]:
        cpu_percent = float(psutil.cpu_percent(interval=None))
        try:
            per_core = [float(value) for value in psutil.cpu_percent(interval=None, percpu=True)]
        except Exception:
            per_core = []
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        primary = Path(os.environ.get("SystemDrive", "C:") + "\\")
        try:
            disk = psutil.disk_usage(str(primary))
            disk_payload = {
                "path": str(primary),
                "percent": float(disk.percent),
                "used": disk.used,
                "total": disk.total,
                "free": disk.free,
            }
        except OSError:
            disk_payload = {
                "path": str(primary),
                "percent": None,
                "used": None,
                "total": None,
                "free": None,
            }

        battery_payload: dict[str, Any] | None = None
        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is not None:
            battery_payload = {
                "percent": round(float(battery.percent), 1),
                "plugged": bool(battery.power_plugged),
                "seconds_left": battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None,
            }

        try:
            uptime = max(0.0, time.time() - psutil.boot_time())
        except Exception:
            uptime = None

        network = self._network()
        processes = self._top_processes()
        disks = self._disks()

        warnings: list[str] = []
        if cpu_percent >= 90:
            warnings.append(f"CPU utilisation is high ({cpu_percent:.0f}%).")
        if memory.percent >= 90:
            warnings.append(f"Memory utilisation is high ({memory.percent:.0f}%).")
        if disk_payload["percent"] is not None and disk_payload["percent"] >= 90:
            warnings.append(f"System drive is almost full ({disk_payload['percent']:.0f}%).")
        if battery_payload and not battery_payload["plugged"] and battery_payload["percent"] <= 15:
            warnings.append("Battery is low and the device is not charging.")
        if not network["up"]:
            warnings.append("No active network interface detected.")

        return {
            "timestamp": utc_now_iso(),
            "cpu": {
                "percent": round(cpu_percent, 1),
                "per_core": per_core,
                "count": psutil.cpu_count(logical=True),
                "physical": psutil.cpu_count(logical=False),
            },
            "memory": {
                "percent": round(float(memory.percent), 1),
                "used": memory.used,
                "available": memory.available,
                "total": memory.total,
            },
            "swap": {
                "percent": round(float(swap.percent), 1),
                "used": swap.used,
                "total": swap.total,
            },
            "disk": disk_payload,
            "disks": disks,
            "network": network,
            "battery": battery_payload,
            "uptime_seconds": uptime,
            "processes": processes,
            "warnings": warnings,
        }


class SystemMonitorService:
    """Samples host metrics off the Qt thread and publishes them on the bus."""

    def __init__(
        self,
        collector: SystemMetricsCollector,
        bus,
        interval_seconds: float = 2.0,
    ) -> None:
        self._collector = collector
        self._bus = bus
        self._interval = max(0.5, float(interval_seconds))

    def set_interval(self, seconds: float) -> None:
        self._interval = max(0.5, min(float(seconds), 30.0))

    async def run(self) -> None:
        log.info("System monitor started (interval %.1fs).", self._interval)
        while True:
            try:
                metrics = await asyncio.to_thread(self._collector.collect)
                self._bus.emit("system.metrics", source="system_monitor", metrics=metrics)
            except asyncio.CancelledError:
                log.info("System monitor stopped.")
                raise
            except Exception:
                log.exception("System metrics sample failed; retrying.")
                await asyncio.sleep(3.0)
                continue
            await asyncio.sleep(self._interval)

