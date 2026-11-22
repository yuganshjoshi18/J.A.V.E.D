"""Redacted, local-only diagnostics collection and export."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from utils.logger import get_logger, redact_text
from utils.paths import AppPaths
from utils.time import utc_now_iso

if TYPE_CHECKING:
    from config.settings import AppSettings

log = get_logger("diagnostics")

_SENSITIVE_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")


def redact_mapping(value: Any, *, key_hint: str = "") -> Any:
    """Recursively redact mappings by key name and value shape."""
    lowered = key_hint.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_mapping(v, key_hint=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item, key_hint=key_hint) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _log_tail(path: Path, max_lines: int = 400) -> str:
    if not path.exists():
        return "(no log file yet)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-max_lines:]
        return redact_text("".join(lines))
    except OSError as exc:
        return f"(log unreadable: {exc})"


def build_report(
    *,
    paths: AppPaths,
    settings: "AppSettings | None",
    health_checks: list[dict[str, Any]],
    database_stats: dict[str, Any],
    app_version: str,
    audit_events: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a diagnostics report. It never contains credentials or raw DB rows."""
    try:
        disk_free = shutil.disk_usage(paths.data_root).free
    except OSError:
        disk_free = None

    report: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "app": {
            "name": "J.A.V.E.D.",
            "version": app_version,
            "phase": 1,
            "phase_name": "Foundation and UI",
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "python_implementation": platform.python_implementation(),
            "architecture": platform.machine(),
            "processor": platform.processor() or "unknown",
            "cpu_count_logical": os.cpu_count(),
            "data_root": str(paths.data_root),
            "data_root_writable": paths.is_writable(),
            "data_root_free_bytes": disk_free,
        },
        "settings": redact_mapping(settings.model_dump(mode="json") if settings else {}),
        "health": redact_mapping(health_checks),
        "database": redact_mapping(database_stats),
        "recent_audit": redact_mapping(audit_events or []),
        "extra": redact_mapping(extra or {}),
    }
    return report


def export_report(
    *,
    report: dict[str, Any],
    paths: AppPaths,
    log_path: Path | None = None,
    settings: "AppSettings | None" = None,
) -> Path:
    """Write a local ZIP containing the report, redacted settings and a log tail.

    The database file, secrets directory, user documents and full logs are
    deliberately excluded.
    """
    paths.exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = paths.exports_dir / f"javed-diagnostics-{stamp}.zip"
    counter = 1
    while target.exists():
        target = paths.exports_dir / f"javed-diagnostics-{stamp}-{counter}.zip"
        counter += 1

    environment_text = "\n".join(
        [
            "J.A.V.E.D. diagnostics",
            f"Generated: {report.get('generated_at')}",
            f"Python: {report['environment']['python']}",
            f"Platform: {report['environment']['platform']}",
            f"Data root: {report['environment']['data_root']}",
            f"Log file: {log_path or '(unknown)'}",
        ]
    )
    settings_payload = redact_mapping(
        settings.model_dump(mode="json") if settings else report.get("settings", {})
    )

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False))
        archive.writestr("environment.txt", environment_text)
        archive.writestr(
            "settings.redacted.json",
            json.dumps(settings_payload, indent=2, ensure_ascii=False),
        )
        if log_path is not None:
            archive.writestr("javed.log.tail.txt", _log_tail(log_path))

    log.info("Diagnostics exported to %s", target)
    return target
