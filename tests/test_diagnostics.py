from __future__ import annotations

import json
import zipfile

from utils.diagnostics import build_report, export_report, redact_mapping
from utils.security import ENV_VAR

SENTINEL = "AIza" + "z" * 32


def test_redact_mapping_removes_secret_keys_and_values() -> None:
    payload = {
        "safe": "visible",
        "api_key": SENTINEL,
        "nested": {"password": "hunter2", "list": [{"token": "abc"}, "ok"]},
    }

    redacted = redact_mapping(payload)

    assert redacted["safe"] == "visible"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["list"][0]["token"] == "[REDACTED]"
    assert redacted["nested"]["list"][1] == "ok"


def test_build_report_has_environment_facts_and_no_key(app_paths, settings_manager, monkeypatch) -> None:
    monkeypatch.setenv(ENV_VAR, SENTINEL)
    settings = settings_manager.load()
    report = build_report(
        paths=app_paths,
        settings=settings,
        health_checks=[{"component": "database", "status": "ok"}],
        database_stats={"schema_version": 1},
        app_version="0.1.0",
        audit_events=[{"category": "app", "detail": f"key={SENTINEL}"}],
        extra={"api_key": SENTINEL, "runtime_tasks": []},
    )

    serialized = json.dumps(report)
    assert SENTINEL not in serialized
    assert report["app"]["phase"] == 1
    assert report["environment"]["data_root"] == str(app_paths.data_root)
    assert report["environment"]["data_root_writable"] is True
    assert report["database"]["schema_version"] == 1
    assert report["health"][0]["component"] == "database"


def test_export_writes_a_redacted_zip(app_paths, settings_manager, monkeypatch) -> None:
    monkeypatch.setenv(ENV_VAR, SENTINEL)
    settings = settings_manager.load()
    app_paths.log_file.write_text(
        f"2026-01-01 | INFO | boot\napi_key={SENTINEL}\n",
        encoding="utf-8",
    )
    report = build_report(
        paths=app_paths,
        settings=settings,
        health_checks=[],
        database_stats={},
        app_version="0.1.0",
        extra={"note": f"Bearer {SENTINEL}"},
    )

    target = export_report(
        report=report,
        paths=app_paths,
        log_path=app_paths.log_file,
        settings=settings,
    )

    assert target.exists()
    assert target.parent == app_paths.exports_dir
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert names == {
            "report.json",
            "environment.txt",
            "settings.redacted.json",
            "javed.log.tail.txt",
        }
        combined = "\n".join(archive.read(name).decode("utf-8") for name in names)

    assert SENTINEL not in combined
    assert "[REDACTED]" in combined
    payload = json.loads(zipfile.ZipFile(target).read("report.json"))
    assert payload["app"]["name"] == "J.A.V.E.D."


def test_export_never_overwrites(app_paths, settings_manager) -> None:
    settings = settings_manager.load()
    report = build_report(
        paths=app_paths,
        settings=settings,
        health_checks=[],
        database_stats={},
        app_version="0.1.0",
    )

    first = export_report(report=report, paths=app_paths)
    second = export_report(report=report, paths=app_paths)

    assert first != second
    assert first.exists() and second.exists()
