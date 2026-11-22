from __future__ import annotations

from core.services.health import HealthService
from memory.database import Database
from utils.security import ENV_VAR, SecretStore

VALID_KEY = "AIza" + "q" * 32


def build_health(app_paths, settings_manager, env=None) -> tuple[HealthService, Database]:
    database = Database(app_paths.database_file)
    database.connect()
    service = HealthService(
        paths=app_paths,
        db=database,
        secrets=SecretStore(app_paths.secrets_dir, env=env or {}),
        settings_manager=settings_manager,
    )
    return service, database


def test_health_reports_real_foundation_state(app_paths, settings_manager) -> None:
    service, database = build_health(app_paths, settings_manager)
    try:
        health = service.check_all()
    finally:
        database.close()

    checks = {check["component"]: check for check in health["checks"]}
    assert health["core_operational"] is True
    assert checks["database"]["status"] == "ok"
    assert checks["storage"]["status"] == "ok"
    assert checks["gemini_key"]["status"] == "not_configured"
    assert checks["gemini_provider"]["status"] == "not_configured"
    assert checks["voice"]["status"] == "unavailable"
    assert checks["local_ai"]["status"] == "unavailable"
    assert checks["agent_engine"]["status"] == "unavailable"
    assert health["overall"] == "not_configured"


def test_configured_key_reports_a_ready_provider_without_faking_connectivity(
    app_paths, settings_manager
) -> None:
    service, database = build_health(
        app_paths,
        settings_manager,
        env={ENV_VAR: VALID_KEY},
    )
    try:
        health = service.check_all()
    finally:
        database.close()

    checks = {check["component"]: check for check in health["checks"]}
    assert checks["gemini_key"]["status"] == "ok"
    assert "fingerprint" in checks["gemini_key"]["detail"]
    assert VALID_KEY not in checks["gemini_key"]["detail"]
    assert checks["gemini_provider"]["status"] == "ok"
    detail = checks["gemini_provider"]["detail"]
    assert "gemini-2.5-flash" in detail
    assert "on demand" in detail
    assert "Connectivity is verified by each real request" in detail


def test_health_reports_database_failure(app_paths, settings_manager, monkeypatch) -> None:
    service, database = build_health(app_paths, settings_manager)
    # Database lazily reconnects on ping(), so simulate an unreachable engine.
    monkeypatch.setattr(database, "ping", lambda: False)
    try:
        health = service.check_all()
    finally:
        database.close()

    checks = {check["component"]: check for check in health["checks"]}
    assert checks["database"]["status"] == "error"
    assert health["core_operational"] is False
    assert health["overall"] == "error"
