"""Command-overview page with live host telemetry and honest readiness."""

from __future__ import annotations

import platform
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings import CURRENT_PHASE
from core.application import ApplicationContext
from ui.components.cards import (
    Card,
    CardHeader,
    EmptyState,
    KeyValueRow,
    PageHeader,
    StatTile,
    StatusPill,
    make_button,
)
from ui.components.visualizer import AssistantVisualizer
from ui.theme import SUCCESS, DANGER
from utils.formatting import format_bytes, format_percent, wrap_path
from utils.time import greeting_for_hour


def _severity(percent: float | None, warning: float = 75.0, critical: float = 90.0) -> str:
    if percent is None:
        return "normal"
    if percent >= critical:
        return "error"
    if percent >= warning:
        return "warning"
    return "normal"


def _short_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%H:%M")
    except ValueError:
        return "—"


class DashboardPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("Page")
        self._health: dict | None = None
        self._last_metrics: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("PageContent")
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(28, 24, 28, 24)
        self.layout_.setSpacing(18)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header = PageHeader(
            "Command Overview",
            "Live foundation telemetry, security posture and delivery readiness.",
            eyebrow="J.A.V.E.D. // Command Console",
        )
        self.header_status = StatusPill("STARTING", "warning")
        header.add_action(self.header_status)
        self.layout_.addWidget(header)

        self.layout_.addWidget(self._build_hero())

        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(14)
        self.cpu_tile = StatTile("CPU", "%")
        self.memory_tile = StatTile("Memory", "%")
        self.disk_tile = StatTile("System drive", "%")
        self.network_tile = StatTile("Network")
        for tile in (self.cpu_tile, self.memory_tile, self.disk_tile, self.network_tile):
            tiles.addWidget(tile)
        self.layout_.addLayout(tiles)

        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(16)
        self.columns_layout.addWidget(self._build_readiness(), 0)
        self.columns_layout.addWidget(self._build_activity(), 0)
        self.columns_layout.setStretch(0, 3)
        self.columns_layout.setStretch(1, 2)
        self.layout_.addLayout(self.columns_layout)

        self.layout_.addWidget(self._build_environment())
        self.layout_.addStretch(1)

        self.header_status.set_status("warning", "Starting")
        self.visualizer.set_state("standby")

    # ------------------------------------------------------------------ hero
    def _build_hero(self) -> Card:
        card = Card(margins=(22, 20, 24, 22), spacing=12)
        card.setObjectName("HeroCard")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(26)

        visual_column = QVBoxLayout()
        visual_column.setContentsMargins(0, 0, 0, 0)
        visual_column.setSpacing(2)
        visual_column.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.visualizer = AssistantVisualizer()
        visual_column.addWidget(self.visualizer, 0, Qt.AlignmentFlag.AlignHCenter)
        core_label = QLabel("ASSISTANT CORE")
        core_label.setObjectName("VisualizerCaption")
        core_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        visual_column.addWidget(core_label)
        self.voice_state = QLabel("STANDBY · VOICE OFFLINE")
        self.voice_state.setObjectName("VisualizerState")
        self.voice_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        visual_column.addWidget(self.voice_state)
        row.addLayout(visual_column, 0)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(8)
        self.greeting = QLabel("Welcome back.")
        self.greeting.setObjectName("Eyebrow")
        text_column.addWidget(self.greeting)
        self.hero_headline = QLabel("Foundation services starting.")
        self.hero_headline.setObjectName("Display")
        self.hero_headline.setWordWrap(True)
        text_column.addWidget(self.hero_headline)
        self.hero_copy = QLabel(
            "Telemetry, configuration, secure key storage and the audit trail are "
            "implemented. Gemini reasoning and voice interaction are scheduled for "
            "Phases 2–3 and are not simulated in this build."
        )
        self.hero_copy.setObjectName("BodyCopy")
        self.hero_copy.setWordWrap(True)
        text_column.addWidget(self.hero_copy)

        pills = QHBoxLayout()
        pills.setContentsMargins(0, 4, 0, 0)
        pills.setSpacing(8)
        self.db_pill = StatusPill("Database", "muted")
        self.storage_pill = StatusPill("Storage", "muted")
        self.monitor_pill = StatusPill("Telemetry", "muted")
        self.key_pill = StatusPill("API key", "muted")
        for pill in (self.db_pill, self.storage_pill, self.monitor_pill, self.key_pill):
            pills.addWidget(pill)
        pills.addStretch(1)
        text_column.addLayout(pills)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 8, 0, 0)
        actions.setSpacing(8)
        diagnostics = make_button("Diagnostics", "primary")
        diagnostics.clicked.connect(lambda: self.navigate_requested.emit("diagnostics"))
        settings_button = make_button("Settings", "ghost")
        settings_button.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        system_button = make_button("System monitor", "ghost")
        system_button.clicked.connect(lambda: self.navigate_requested.emit("system"))
        actions.addWidget(diagnostics)
        actions.addWidget(settings_button)
        actions.addWidget(system_button)
        actions.addStretch(1)
        text_column.addLayout(actions)
        text_column.addStretch(1)

        row.addLayout(text_column, 1)
        card.body.addLayout(row)
        return card

    # ------------------------------------------------------------- readiness
    def _build_readiness(self) -> Card:
        card = Card()
        self.recheck_button = make_button("Re-check", "ghost")
        self.recheck_button.clicked.connect(self._recheck)
        card.body.addWidget(
            CardHeader(
                "Capability readiness",
                "Reported from the running services and configuration.",
                action=self.recheck_button,
            )
        )
        self.readiness_container = QWidget()
        self.readiness_layout = QVBoxLayout(self.readiness_container)
        self.readiness_layout.setContentsMargins(0, 2, 0, 0)
        self.readiness_layout.setSpacing(7)
        card.body.addWidget(self.readiness_container)
        card.body.addStretch(1)
        return card

    def _recheck(self) -> None:
        self.recheck_button.setEnabled(False)
        self.recheck_button.setText("Checking…")
        try:
            self.context.refresh_health()
        finally:
            self.recheck_button.setEnabled(True)
            self.recheck_button.setText("Re-check")

    # -------------------------------------------------------------- activity
    def _build_activity(self) -> Card:
        card = Card()
        refresh = make_button("Refresh", "ghost")
        refresh.clicked.connect(self.refresh_activity)
        card.body.addWidget(
            CardHeader(
                "Recent activity",
                "Durable local audit trail.",
                action=refresh,
            )
        )
        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 2, 0, 0)
        self.activity_layout.setSpacing(8)
        card.body.addWidget(self.activity_container)
        card.body.addStretch(1)
        return card

    # ----------------------------------------------------------- environment
    def _build_environment(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Environment",
                "Read-only facts about this installation.",
                action=self._open_data_button(),
            )
        )
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(2)
        self.env_python = KeyValueRow("Python", platform.python_version(), mono=True)
        self.env_qt = KeyValueRow("Qt / PySide6", self._qt_version(), mono=True)
        self.env_model = KeyValueRow("Configured model", self.context.settings.gemini.model, mono=True)
        self.env_permission = KeyValueRow(
            "Permission level",
            f"Level {self.context.settings.agents.permission_level} (read-only default)",
        )
        self.env_data = KeyValueRow(
            "Data directory", wrap_path(str(self.context.paths.data_root)), mono=True
        )
        self.env_log = KeyValueRow(
            "Log file", wrap_path(str(self.context.paths.log_file)), mono=True
        )
        self.env_schema = KeyValueRow(
            "Database", f"schema v{self.context.db.schema_version()} · SQLite WAL", mono=True
        )
        rows = [
            self.env_python,
            self.env_qt,
            self.env_model,
            self.env_permission,
            self.env_data,
            self.env_log,
            self.env_schema,
        ]
        for index, widget in enumerate(rows):
            grid.addWidget(widget, index // 2, index % 2)
        card.body.addLayout(grid)
        return card

    @staticmethod
    def _qt_version() -> str:
        from PySide6.QtCore import qVersion

        return f"{qVersion()} / PySide6"

    def _open_data_button(self):
        button = make_button("Open data folder", "ghost")
        button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.context.paths.data_root)))
        )
        return button

    # ---------------------------------------------------------------- layout
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        vertical = self.width() < 1050
        direction = (
            QBoxLayout.Direction.TopToBottom
            if vertical
            else QBoxLayout.Direction.LeftToRight
        )
        if self.columns_layout.direction() != direction:
            self.columns_layout.setDirection(direction)
            self.columns_layout.setStretch(0, 0 if vertical else 3)
            self.columns_layout.setStretch(1, 0 if vertical else 2)

    # ---------------------------------------------------------------- update
    def update_clock(self, now: datetime) -> None:
        self.greeting.setText(f"{greeting_for_hour(now.hour).upper()} · PHASE {CURRENT_PHASE:02d}")

    def set_app_state(self, state: dict) -> None:
        status = str(state.get("status", "starting"))
        mapping = {
            "ready": ("ok", "Core online", "standby"),
            "starting": ("warning", "Starting", "standby"),
            "degraded": ("error", "Degraded", "error"),
            "shutting_down": ("muted", "Shutting down", "offline"),
            "stopped": ("muted", "Stopped", "offline"),
        }
        tone, text, visual = mapping.get(status, ("muted", status.title(), "offline"))
        self.header_status.set_status(tone, text)
        if status == "ready":
            self.hero_headline.setText("Foundation online.")
        elif status == "degraded":
            self.hero_headline.setText("Foundation degraded.")
            self.hero_copy.setText(
                state.get("last_error")
                or "A core service reported a problem. Open Diagnostics for verified details."
            )
        elif status == "starting":
            self.hero_headline.setText("Foundation services starting.")
        else:
            self.hero_headline.setText("Foundation stopped.")
        self.visualizer.set_state(visual)
        self.voice_state.setText(
            "STANDBY · VOICE OFFLINE" if status == "ready" else status.upper()
        )

    def set_health(self, health: dict) -> None:
        self._health = health
        checks = {check["component"]: check for check in health.get("checks", [])}
        database = checks.get("database", {})
        storage = checks.get("storage", {})
        key = checks.get("gemini_key", {})
        self.db_pill.set_status(database.get("status", "muted"), "Database")
        self.storage_pill.set_status(storage.get("status", "muted"), "Storage")
        self.key_pill.set_status(
            "ok" if key.get("status") == "ok" else "warning",
            "API key" if key.get("status") == "ok" else "No API key",
        )
        monitor_task = self.context.tasks.snapshot()
        monitor_live = any(
            task["name"] == "system_monitor" and task["status"] == "running"
            for task in monitor_task
        )
        self.monitor_pill.set_status("ok" if monitor_live else "warning", "Telemetry")

        while self.readiness_layout.count():
            item = self.readiness_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for check in health.get("checks", []):
            row = QWidget()
            layout = QGridLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(10)
            layout.setVerticalSpacing(1)
            label = QLabel(check.get("label", check.get("component", "Component")))
            label.setObjectName("ReadinessName")
            pill = StatusPill(check.get("status", "muted"))
            pill.setMinimumWidth(88)
            detail = QLabel(wrap_path(check.get("detail", "")))
            detail.setObjectName("ReadinessDetail")
            detail.setWordWrap(True)
            layout.addWidget(label, 0, 0)
            layout.addWidget(pill, 0, 1, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(detail, 1, 0, 1, 2)
            layout.setColumnStretch(0, 1)
            self.readiness_layout.addWidget(row)

        if health.get("core_operational"):
            self.hero_headline.setText("Foundation online.")
            self.header_status.set_status("ok", "Core online")
        else:
            self.hero_headline.setText("Foundation degraded.")
            self.header_status.set_status("error", "Degraded")

    def update_metrics(self, metrics: dict) -> None:
        self._last_metrics = metrics
        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})
        network = metrics.get("network", {})
        cpu_percent = cpu.get("percent")
        memory_percent = memory.get("percent")
        disk_percent = disk.get("percent")

        self.cpu_tile.set_metric(
            format_percent(cpu_percent, digits=0),
            detail=f"{cpu.get('count') or '?'} logical cores",
            percent=cpu_percent,
            severity=_severity(cpu_percent),
        )
        self.memory_tile.set_metric(
            format_percent(memory_percent, digits=0),
            detail=(
                f"{format_bytes(memory.get('used'))} of {format_bytes(memory.get('total'))} in use"
                if memory.get("total")
                else "Memory data unavailable"
            ),
            percent=memory_percent,
            severity=_severity(memory_percent),
        )
        self.disk_tile.set_metric(
            format_percent(disk_percent, digits=0),
            detail=(
                f"{format_bytes(disk.get('free'))} free on {disk.get('path', 'system drive')}"
                if disk.get("free") is not None
                else "Disk data unavailable"
            ),
            percent=disk_percent,
            severity=_severity(disk_percent),
        )
        rate_down = network.get("rate_recv") or 0.0
        rate_up = network.get("rate_sent") or 0.0
        self.network_tile.set_metric(
            format_bytes(rate_down, per_second=True),
            detail=f"↑ {format_bytes(rate_up, per_second=True)} · link {'up' if network.get('up') else 'down'}",
            percent=None,
        )

    def refresh_activity(self) -> None:
        entries = self.context.audit.recent(8)
        self.set_audit(entries)

    def set_audit(self, entries: list[dict]) -> None:
        while self.activity_layout.count():
            item = self.activity_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not entries:
            self.activity_layout.addWidget(EmptyState("No audit events recorded yet."))
            return
        for entry in entries:
            row = QWidget()
            layout = QGridLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(8)
            layout.setVerticalSpacing(0)
            dot = QLabel("●")
            dot.setObjectName("ActivityDot")
            ok = bool(entry.get("success", True))
            dot.setStyleSheet(f"color: {SUCCESS if ok else DANGER}; font-size: 8px;")
            title = QLabel(
                f"{entry.get('category', 'event').title()} · "
                f"{str(entry.get('action', '')).replace('_', ' ').capitalize()}"
            )
            title.setObjectName("ActivityTitle")
            stamp = QLabel(_short_time(entry.get("timestamp", "")))
            stamp.setObjectName("MonoMuted")
            layout.addWidget(dot, 0, 0)
            layout.addWidget(title, 0, 1)
            layout.addWidget(stamp, 0, 2, Qt.AlignmentFlag.AlignRight)
            detail_text = str(entry.get("detail", "")).strip()
            if detail_text:
                detail = QLabel(detail_text[:120])
                detail.setObjectName("ActivityDetail")
                detail.setWordWrap(True)
                layout.addWidget(detail, 1, 1, 1, 2)
            layout.setColumnStretch(1, 1)
            self.activity_layout.addWidget(row)
        self.activity_layout.addStretch(1)

    def refresh_environment(self) -> None:
        settings = self.context.settings
        self.env_model.setText_value(settings.gemini.model)
        self.env_permission.setText_value(
            f"Level {settings.agents.permission_level} "
            f"({'read-only' if settings.agents.permission_level == 1 else 'configured'})"
        )
        self.env_schema.setText_value(
            f"schema v{self.context.db.schema_version()} · SQLite WAL · "
            f"{self.context.audit_repository.count()} audit events"
        )
