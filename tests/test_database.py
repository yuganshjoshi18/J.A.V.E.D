from __future__ import annotations

import pytest

from memory.database import SCHEMA_VERSION, Database
from memory.repositories import AuditRepository, SettingsRepository, TaskRepository


@pytest.fixture
def db(app_paths):
    database = Database(app_paths.database_file)
    database.connect()
    try:
        yield database
    finally:
        database.close()


def test_schema_is_created_and_idempotent(db: Database) -> None:
    assert db.schema_version() == SCHEMA_VERSION
    assert db.ping() is True

    stats = db.stats()
    assert stats["journal_mode"] == "wal"
    assert stats["schema_version"] == SCHEMA_VERSION
    assert stats["file_size_bytes"] > 0
    assert set(stats["table_counts"]) >= {
        "settings",
        "audit_events",
        "conversations",
        "messages",
        "tasks",
        "task_steps",
        "memories",
        "notes",
        "research_reports",
        "skills",
    }

    db.close()
    db.connect()
    assert db.schema_version() == SCHEMA_VERSION


def test_queries_are_parameterised(db: Database) -> None:
    db.execute("INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)", ("a", "1", "now"))
    row = db.query_one("SELECT value FROM settings WHERE key = ?", ("a",))
    assert row == {"value": "1"}
    assert db.query_one("SELECT value FROM settings WHERE key = ?", ("a' OR '1'='1",)) is None


def test_settings_repository_round_trip(db: Database) -> None:
    repository = SettingsRepository(db)
    assert repository.get("missing", "fallback") == "fallback"

    repository.set("ui.theme", {"name": "navy", "dark": True})
    assert repository.get("ui.theme") == {"name": "navy", "dark": True}
    repository.set("ui.theme", {"name": "navy", "dark": False})
    assert repository.get("ui.theme") == {"name": "navy", "dark": False}
    assert repository.all() == {"ui.theme": {"name": "navy", "dark": False}}

    repository.delete("ui.theme")
    assert repository.get("ui.theme") is None


def test_audit_repository_records_orders_and_prunes(db: Database) -> None:
    repository = AuditRepository(db)
    first = repository.record("app", "started", detail="boot", actor="system")
    second = repository.record("settings", "saved", detail="theme", success=False)

    assert first > 0
    assert second > first
    entries = repository.recent(10)
    assert [entry.action for entry in entries] == ["saved", "started"]
    assert entries[0].success is False
    assert repository.count() == 2

    db.execute(
        "INSERT INTO audit_events(timestamp, category, action) VALUES (?, ?, ?)",
        ("2000-01-01T00:00:00+00:00", "old", "event"),
    )
    assert repository.prune(1) == 1
    assert repository.count() == 2


def test_task_repository_lifecycle(db: Database) -> None:
    repository = TaskRepository(db)
    task = repository.create(
        "Review report",
        goal="Check the draft",
        priority=3,
        metadata={"source": "test"},
    )

    fetched = repository.get(task.id)
    assert fetched is not None
    assert fetched.title == "Review report"
    assert fetched.priority == 3
    assert fetched.metadata == {"source": "test"}
    assert fetched.status == "pending"

    assert repository.set_status(task.id, "completed") is True
    assert repository.counts_by_status() == {"completed": 1}
    completed = repository.list(status="completed")
    assert [item.id for item in completed] == [task.id]
    assert repository.list(status="failed") == []
    assert repository.set_status("missing", "failed") is False


def test_priority_is_clamped(db: Database) -> None:
    repository = TaskRepository(db)
    task = repository.create("Clamped", priority=99)
    assert task.priority == 4


def test_transaction_rolls_back_on_error(db: Database) -> None:
    repository = SettingsRepository(db)

    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                ("rolled-back", "1", "now"),
            )
            raise RuntimeError("abort")

    assert repository.get("rolled-back") is None
