"""Runtime composition root: owns services and their lifecycle.

The Qt layer receives this context; it does not construct databases, loops or
monitors itself. This keeps startup/shutdown ordering testable without widgets.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai.gemini_provider import GeminiProvider
from config.settings import (
    APP_VERSION,
    CURRENT_PHASE,
    CURRENT_PHASE_NAME,
    AppSettings,
    SettingsManager,
)
from core.async_runtime import AsyncRuntime
from core.audit import AuditService
from core.event_manager import EventBus
from core.services.chat import ChatService
from core.services.health import HealthService
from core.services.system_monitor import SystemMetricsCollector, SystemMonitorService
from core.state_manager import AppStatus, StateManager
from core.task_manager import TaskManager
from memory.database import Database
from memory.repositories import (
    AuditRepository,
    ConversationRepository,
    TaskRepository,
)
from utils.diagnostics import build_report, export_report
from utils.logger import get_logger
from utils.paths import AppPaths, resolve_paths
from utils.security import SecretStore

log = get_logger("application")


@dataclass
class ApplicationContext:
    """Owns every non-UI service for one application instance."""

    paths: AppPaths
    settings_manager: SettingsManager
    settings: AppSettings
    secrets: SecretStore
    db: Database
    bus: EventBus
    state: StateManager
    runtime: AsyncRuntime
    tasks: TaskManager
    audit: AuditService
    audit_repository: AuditRepository
    task_repository: TaskRepository
    conversation_repository: ConversationRepository
    provider: GeminiProvider
    chat: ChatService
    collector: SystemMetricsCollector
    monitor: SystemMonitorService
    health: HealthService
    _started: bool = field(default=False, init=False)
    _stopping: bool = field(default=False, init=False)
    _monitor_task_id: str | None = field(default=None, init=False)

    @classmethod
    def create(cls, paths: AppPaths | None = None) -> "ApplicationContext":
        resolved = paths or resolve_paths()
        resolved.ensure()
        settings_manager = SettingsManager(resolved)
        settings = settings_manager.load()

        secrets = SecretStore(resolved.secrets_dir)
        db = Database(resolved.database_file)
        db.connect()

        runtime = AsyncRuntime()
        bus = EventBus(loop_provider=lambda: runtime.loop)
        state = StateManager(bus)
        audit_repository = AuditRepository(db)
        task_repository = TaskRepository(db)
        conversation_repository = ConversationRepository(db)
        audit = AuditService(audit_repository, bus)
        tasks = TaskManager(runtime.loop, bus)
        provider = GeminiProvider(
            secrets=secrets,
            settings_provider=lambda: settings_manager.load().gemini,
        )
        chat = ChatService(
            conversations=conversation_repository,
            provider=provider,
            tasks=tasks,
            bus=bus,
            audit=audit,
            settings_provider=settings_manager.load,
        )
        collector = SystemMetricsCollector(top_process_count=settings.monitor.top_process_count)
        monitor = SystemMonitorService(collector, bus, settings.monitor.refresh_seconds)
        health = HealthService(
            paths=resolved,
            db=db,
            secrets=secrets,
            settings_manager=settings_manager,
        )

        return cls(
            paths=resolved,
            settings_manager=settings_manager,
            settings=settings,
            secrets=secrets,
            db=db,
            bus=bus,
            state=state,
            runtime=runtime,
            tasks=tasks,
            audit=audit,
            audit_repository=audit_repository,
            task_repository=task_repository,
            conversation_repository=conversation_repository,
            provider=provider,
            chat=chat,
            collector=collector,
            monitor=monitor,
            health=health,
        )

    def start(self) -> None:
        if self._started:
            return
        self.runtime.start()
        self.state.transition(AppStatus.STARTING, "Starting foundation services")
        self.audit.record(
            "app",
            "started",
            detail={
                "version": APP_VERSION,
                "phase": CURRENT_PHASE,
                "python": sys.version.split()[0],
                "model": self.settings.gemini.model,
                "provider_configured": self.provider.configured,
                "permission_level": self.settings.agents.permission_level,
                "settings_issue": self.settings_manager.last_issue,
            },
        )

        health = self.health.check_all()
        self.bus.emit("health.checked", source="health", health=health)
        if health["core_operational"]:
            self.state.transition(AppStatus.READY, "Foundation services online")
        else:
            self.state.set_error("Core services are degraded. Review Diagnostics.")

        self._monitor_task_id = self.tasks.start("system_monitor", self.monitor.run)
        self._started = True
        log.info(
            "J.A.V.E.D. %s started — Phase %s (%s).",
            APP_VERSION,
            CURRENT_PHASE,
            CURRENT_PHASE_NAME,
        )

    def refresh_health(self) -> dict[str, Any]:
        health = self.health.check_all()
        self.bus.emit("health.checked", source="health", health=health)
        return health

    def save_settings(self, settings: AppSettings) -> AppSettings:
        saved = self.settings_manager.save(settings)
        self.settings = saved
        self.monitor.set_interval(saved.monitor.refresh_seconds)
        self.collector.set_top_process_count(saved.monitor.top_process_count)
        self.state.update(memory_enabled=saved.memory.enabled)
        self.audit.record(
            "settings",
            "saved",
            detail={
                "model": saved.gemini.model,
                "permission_level": saved.agents.permission_level,
                "memory_enabled": saved.memory.enabled,
                "workspace_count": len(saved.security.allowed_workspaces),
            },
            actor="user",
        )
        self.bus.emit("settings.changed", source="application", settings=saved)
        return saved

    def export_diagnostics(self) -> Path:
        checks = self.health.check_all()["checks"]
        report = build_report(
            paths=self.paths,
            settings=self.settings,
            health_checks=checks,
            database_stats=self.db.stats(),
            app_version=APP_VERSION,
            audit_events=self.audit.recent(25),
            extra={
                "runtime_tasks": self.tasks.snapshot(),
                "monitor_task_id": self._monitor_task_id,
                "phase": CURRENT_PHASE,
                "phase_name": CURRENT_PHASE_NAME,
            },
        )
        target = export_report(
            report=report,
            paths=self.paths,
            log_path=self.paths.log_file,
            settings=self.settings,
        )
        self.audit.record(
            "diagnostics",
            "exported",
            detail={"file": target.name},
            actor="user",
        )
        return target

    def shutdown(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        try:
            self.state.transition(AppStatus.SHUTTING_DOWN, "Stopping services")
            self.audit.record("app", "stopped", detail={"reason": "shutdown"})
            self.tasks.cancel_all()
            self.runtime.shutdown(timeout=5.0)
        finally:
            self.provider.close()
            self.db.close()
            self.state.transition(AppStatus.STOPPED, "Application stopped")
            log.info("J.A.V.E.D. shutdown complete.")
