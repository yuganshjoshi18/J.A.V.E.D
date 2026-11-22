"""Capability readiness and health reporting.

Health tells the truth about what exists. A configured API key is not reported
as a live provider, and planned voice/local-AI features are explicitly marked
unavailable rather than faked.
"""

from __future__ import annotations

import shutil
from typing import Any

from config.settings import AppSettings, SettingsManager
from memory.database import Database
from utils.logger import get_logger
from utils.paths import AppPaths
from utils.security import SecretStore
from utils.time import utc_now_iso

log = get_logger("health")

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UNAVAILABLE = "unavailable"

_SEVERITY = {
    STATUS_ERROR: 4,
    STATUS_WARNING: 3,
    STATUS_NOT_CONFIGURED: 2,
    STATUS_UNAVAILABLE: 1,
    STATUS_OK: 0,
}


class HealthService:
    def __init__(
        self,
        *,
        paths: AppPaths,
        db: Database,
        secrets: SecretStore,
        settings_manager: SettingsManager,
    ) -> None:
        self._paths = paths
        self._db = db
        self._secrets = secrets
        self._settings_manager = settings_manager

    @property
    def settings(self) -> AppSettings:
        return self._settings_manager.load()

    def check_all(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        database_ok = self._db.ping()
        checks.append(
            {
                "component": "database",
                "label": "SQLite database",
                "status": STATUS_OK if database_ok else STATUS_ERROR,
                "detail": (
                    f"Schema v{self._db.schema_version()} · {self._paths.database_file.name}"
                    if database_ok
                    else "Database ping failed."
                ),
            }
        )

        writable = self._paths.is_writable()
        free_bytes = self._free_disk_bytes()
        storage_status = STATUS_OK
        storage_detail = f"{self._paths.data_root} is writable."
        if not writable:
            storage_status = STATUS_ERROR
            storage_detail = "Application data directory is not writable."
        elif free_bytes is not None and free_bytes < 1024**3:
            storage_status = STATUS_WARNING
            storage_detail = "Less than 1 GB free in the data directory."
        checks.append(
            {
                "component": "storage",
                "label": "Local storage",
                "status": storage_status,
                "detail": storage_detail,
            }
        )

        secret_status = self._secrets.status()
        checks.append(
            {
                "component": "gemini_key",
                "label": "Gemini API key",
                "status": STATUS_OK if secret_status.configured else STATUS_NOT_CONFIGURED,
                "detail": (
                    f"Configured via {secret_status.storage} (fingerprint {secret_status.fingerprint})."
                    if secret_status.configured
                    else "No key configured. Add one in Settings or set GEMINI_API_KEY."
                ),
            }
        )
        checks.append(
            {
                "component": "gemini_provider",
                "label": "Gemini intelligence",
                "status": STATUS_OK if secret_status.configured else STATUS_NOT_CONFIGURED,
                "detail": (
                    f"Ready to call {self.settings.gemini.model} on demand "
                    f"({self.settings.gemini.max_retries} retries, "
                    f"{self.settings.gemini.timeout_seconds:.0f}s timeout, "
                    f"streaming={'on' if self.settings.gemini.streaming else 'off'}). "
                    "Connectivity is verified by each real request."
                    if secret_status.configured
                    else "No API key configured; conversation requests are refused until one is added."
                ),
            }
        )

        voice_status = STATUS_UNAVAILABLE
        checks.append(
            {
                "component": "voice",
                "label": "Voice input / output",
                "status": voice_status,
                "detail": "Local STT, TTS and wake word arrive in Phase 3.",
            }
        )
        checks.append(
            {
                "component": "local_ai",
                "label": "Local language model",
                "status": STATUS_UNAVAILABLE,
                "detail": "Ollama routing arrives in Phase 11.",
            }
        )
        checks.append(
            {
                "component": "agent_engine",
                "label": "Agent orchestration",
                "status": STATUS_UNAVAILABLE,
                "detail": "Planning and execution loop arrives in Phase 7.",
            }
        )

        overall = STATUS_OK
        for check in checks:
            if _SEVERITY.get(check["status"], 0) > _SEVERITY.get(overall, 0):
                overall = check["status"]

        return {
            "checked_at": utc_now_iso(),
            "overall": overall,
            "core_operational": database_ok and writable,
            "checks": checks,
        }

    def _free_disk_bytes(self) -> int | None:
        try:
            return shutil.disk_usage(self._paths.data_root).free
        except OSError:
            return None
