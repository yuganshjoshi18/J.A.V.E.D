from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QLabel, QScrollArea

from core.application import ApplicationContext
from ui.components.coming_soon import ComingSoonPage
from ui.event_bridge import EventBridge
from ui.main_window import MainWindow

pytestmark = pytest.mark.ui

NAV_KEYS = [
    "dashboard",
    "chat",
    "agents",
    "tasks",
    "memory",
    "research",
    "files",
    "skills",
    "system",
    "diagnostics",
    "settings",
]


def wait_until(qapp, predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_window_boots_and_every_page_runs(qapp, app_paths, tmp_path) -> None:
    context = ApplicationContext.create(app_paths)
    context.start()
    bridge = EventBridge(context.bus)
    window = MainWindow(context, bridge)
    window.show()

    try:
        assert window.windowTitle().startswith("J.A.V.E.D.")
        assert set(window._pages) == set(NAV_KEYS)
        assert window.stack.count() == len(NAV_KEYS)

        for key in NAV_KEYS:
            window.go_to(key)
            qapp.processEvents()
            page = window._pages[key]
            assert window.stack.currentWidget() is page, key
            for scroll in page.findChildren(QScrollArea):
                assert scroll.horizontalScrollBar().maximum() == 0, f"{key} overflows horizontally"

        # The monitor task is real and registered before the window was built.
        window.go_to("tasks")
        qapp.processEvents()
        assert window.task_page.table.rowCount() >= 1
        task_names = {
            window.task_page.table.item(row, 0).text()
            for row in range(window.task_page.table.rowCount())
        }
        assert "system_monitor" in task_names

        # Real host telemetry arrives on the Qt thread through the event bridge.
        window.go_to("dashboard")
        assert wait_until(
            qapp,
            lambda: window.dashboard_page.cpu_tile.value_label.text() != "—",
        )
        context.refresh_health()
        qapp.processEvents()
        assert window.dashboard_page.db_pill.property("tone") in {"ok", "warning"}
        assert window.dashboard_page.monitor_pill.property("tone") == "ok"

        screenshot = window.grab()
        assert not screenshot.isNull()
        assert screenshot.width() > 1000
        assert screenshot.height() > 700
        target = tmp_path / "window.png"
        assert screenshot.save(str(target))
        assert target.stat().st_size > 0

        assert window.top_status.property("tone") == "ok"
    finally:
        window.close()
        qapp.processEvents()
        bridge.close()
        context.shutdown()

    assert context.state.snapshot.status == "stopped"


def test_phase_locked_pages_are_honest(qapp, app_paths) -> None:
    context = ApplicationContext.create(app_paths)
    bridge = EventBridge(context.bus)
    window = MainWindow(context, bridge)
    expected_phase = {
        "agents": 7,
        "memory": 5,
        "research": 9,
        "files": 6,
        "skills": 13,
    }
    try:
        for key, phase in expected_phase.items():
            page = window._pages[key]
            assert isinstance(page, ComingSoonPage)
            text = "\n".join(label.text() for label in page.findChildren(QLabel))
            assert "NOT YET AVAILABLE" in text
            assert f"Phase {phase}" in text
            assert "simulated data" in text.lower()
            window.go_to(key)
            qapp.processEvents()
            assert window.stack.currentWidget() is page
    finally:
        window.close()
        qapp.processEvents()
        bridge.close()
        context.shutdown()
