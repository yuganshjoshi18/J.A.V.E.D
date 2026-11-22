"""SQLite storage with explicit migrations and thread-safe access.

A single connection guarded by a re-entrant lock is intentional: desktop-scale
traffic is low, and it eliminates cross-thread connection confusion while WAL
mode keeps readers fast. Every query is parameterised.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from utils.logger import get_logger

log = get_logger("database")

SCHEMA_VERSION = 1

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    category    TEXT NOT NULL,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'system',
    detail      TEXT NOT NULL DEFAULT '',
    success     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category);

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'New conversation',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    token_count     INTEGER,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    goal           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    priority       INTEGER NOT NULL DEFAULT 2,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    due_at         TEXT,
    metadata_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);

CREATE TABLE IF NOT EXISTS task_steps (
    id            TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    step_index    INTEGER NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    detail        TEXT NOT NULL DEFAULT '',
    agent         TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    UNIQUE(task_id, step_index)
);
CREATE INDEX IF NOT EXISTS idx_steps_task ON task_steps(task_id, step_index);

CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    content      TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'user',
    confidence   REAL NOT NULL DEFAULT 1.0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    expires_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);

CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    query       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    version     TEXT NOT NULL DEFAULT '0.0.0',
    enabled     INTEGER NOT NULL DEFAULT 1,
    risk_level  TEXT NOT NULL DEFAULT 'low',
    config_json TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL
);
"""

_MIGRATIONS: list[tuple[int, str]] = [(1, _MIGRATION_1)]

_KNOWN_TABLES = (
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
)


class Database:
    """Owns the application SQLite connection and schema lifecycle."""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected.")
        return self._connection

    def connect(self) -> None:
        with self._lock:
            if self._connection is not None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self._path,
                timeout=self._busy_timeout_ms / 1000,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)}")
            self._connection = connection
            self._migrate()
            log.info("Database ready at %s (schema v%s)", self._path, SCHEMA_VERSION)

    def _migrate(self) -> None:
        connection = self.connection
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        current = int(row["version"] or 0) if row else 0
        from utils.time import utc_now_iso

        for version, script in sorted(_MIGRATIONS):
            if version <= current:
                continue
            log.info("Applying database migration v%s", version)
            try:
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now_iso()),
                )
                connection.commit()
            except sqlite3.Error:
                connection.rollback()
                log.exception("Database migration v%s failed", version)
                raise

    def _ensure_connected(self) -> None:
        if self._connection is None:
            self.connect()

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_connected()
            try:
                rows = self.connection.execute(sql, params).fetchall()
            except sqlite3.Error:
                log.exception("Query failed: %s", sql)
                raise
            return [dict(row) for row in rows]

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            self._ensure_connected()
            try:
                row = self.connection.execute(sql, params).fetchone()
            except sqlite3.Error:
                log.exception("Query failed: %s", sql)
                raise
            return dict(row) if row else None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute one statement and return lastrowid (or 0 for non-inserts)."""
        with self._lock:
            self._ensure_connected()
            try:
                cursor = self.connection.execute(sql, params)
                self.connection.commit()
                return int(cursor.lastrowid or 0)
            except sqlite3.Error:
                self.connection.rollback()
                log.exception("Write failed: %s", sql)
                raise

    def execute_many(self, sql: str, rows: list[tuple[Any, ...]]) -> int:
        with self._lock:
            self._ensure_connected()
            try:
                cursor = self.connection.executemany(sql, rows)
                self.connection.commit()
                return int(cursor.rowcount)
            except sqlite3.Error:
                self.connection.rollback()
                log.exception("Bulk write failed: %s", sql)
                raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._ensure_connected()
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def ping(self) -> bool:
        try:
            row = self.query_one("SELECT 1 AS ok")
            return bool(row and row.get("ok") == 1)
        except Exception:
            return False

    def schema_version(self) -> int:
        row = self.query_one("SELECT MAX(version) AS version FROM schema_migrations")
        return int(row["version"] or 0) if row else 0

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in _KNOWN_TABLES:
            row = self.query_one(f"SELECT COUNT(*) AS count FROM {table}")
            counts[table] = int(row["count"]) if row else 0
        return counts

    def stats(self) -> dict[str, Any]:
        counts = self.table_counts()
        file_size = 0
        try:
            file_size = self._path.stat().st_size
        except OSError:
            pass
        journal_mode = self.query_one("PRAGMA journal_mode")
        page_count = self.query_one("PRAGMA page_count")
        return {
            "path": str(self._path),
            "file_size_bytes": file_size,
            "schema_version": self.schema_version(),
            "journal_mode": (journal_mode or {}).get("journal_mode"),
            "page_count": (page_count or {}).get("page_count"),
            "table_counts": counts,
        }

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.commit()
                except sqlite3.Error:
                    pass
                self._connection.close()
                self._connection = None
                log.info("Database connection closed.")
