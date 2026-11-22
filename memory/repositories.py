"""Repositories for persisted application state.

Phase 1 owns configuration, audit and task records. Phase 2 adds conversation
and message persistence; feature-specific repositories arrive with their own
phases.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from memory.database import Database
from memory.models import (
    AuditEntry,
    ConversationRecord,
    MessageRecord,
    TaskRecord,
    TaskStatus,
)
from utils.time import utc_now_iso


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, payload, utc_now_iso()),
        )

    def delete(self, key: str) -> None:
        self._db.execute("DELETE FROM settings WHERE key = ?", (key,))

    def all(self) -> dict[str, Any]:
        rows = self._db.query_all("SELECT key, value FROM settings")
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = None
        return result


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        category: str,
        action: str,
        *,
        detail: str = "",
        actor: str = "system",
        success: bool = True,
    ) -> int:
        return self._db.execute(
            """
            INSERT INTO audit_events(timestamp, category, action, actor, detail, success)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (utc_now_iso(), category, action, actor, detail, int(success)),
        )

    def recent(self, limit: int = 20) -> list[AuditEntry]:
        safe_limit = max(1, min(int(limit), 500))
        rows = self._db.query_all(
            """
            SELECT id, timestamp, category, action, actor, detail, success
            FROM audit_events ORDER BY id DESC LIMIT ?
            """,
            (safe_limit,),
        )
        return [
            AuditEntry(
                id=row["id"],
                timestamp=row["timestamp"],
                category=row["category"],
                action=row["action"],
                actor=row["actor"],
                detail=row["detail"],
                success=bool(row["success"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS count FROM audit_events")
        return int(row["count"]) if row else 0

    def prune(self, retention_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM audit_events WHERE timestamp < ?",
                (cutoff.isoformat(timespec="seconds"),),
            )
            return int(cursor.rowcount)


class ConversationRepository:
    """Conversation headers and their ordered message history."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, title: str = "New conversation") -> ConversationRecord:
        now = utc_now_iso()
        conversation_id = f"cnv_{uuid.uuid4().hex[:12]}"
        clean_title = _clean_title(title) or "New conversation"
        self._db.execute(
            """
            INSERT INTO conversations(id, title, created_at, updated_at, archived)
            VALUES (?, ?, ?, ?, 0)
            """,
            (conversation_id, clean_title, now, now),
        )
        return ConversationRecord(
            id=conversation_id,
            title=clean_title,
            created_at=now,
            updated_at=now,
            archived=False,
        )

    def get(self, conversation_id: str) -> ConversationRecord | None:
        row = self._db.query_one(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        return self._to_conversation(row) if row else None

    def list(
        self,
        *,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[ConversationRecord]:
        safe_limit = max(1, min(int(limit), 500))
        if include_archived:
            rows = self._db.query_all(
                "SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                (safe_limit,),
            )
        else:
            rows = self._db.query_all(
                """
                SELECT * FROM conversations WHERE archived = 0
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (safe_limit,),
            )
        return [self._to_conversation(row) for row in rows]

    def rename(self, conversation_id: str, title: str) -> bool:
        clean_title = _clean_title(title)
        if not clean_title:
            raise ValueError("Conversation title must not be empty.")
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (clean_title, utc_now_iso(), conversation_id),
            )
            return cursor.rowcount > 0

    def add_message(
        self,
        conversation_id: str,
        role: Literal["user", "assistant"],
        content: str,
        *,
        token_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        if role not in ("user", "assistant"):
            raise ValueError(f"Unsupported message role: {role}")
        if not content or not content.strip():
            raise ValueError("Message content must not be empty.")
        now = utc_now_iso()
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        metadata_payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            if cursor.fetchone() is None:
                raise KeyError(f"Unknown conversation: {conversation_id}")
            connection.execute(
                """
                INSERT INTO messages(
                    id, conversation_id, role, content, created_at,
                    token_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    now,
                    token_count,
                    metadata_payload,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return MessageRecord(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
            token_count=token_count,
            metadata=metadata or {},
        )

    def messages(
        self,
        conversation_id: str,
        *,
        limit: int = 200,
    ) -> list[MessageRecord]:
        safe_limit = max(1, min(int(limit), 2000))
        rows = self._db.query_all(
            """
            SELECT * FROM messages WHERE conversation_id = ?
            ORDER BY created_at ASC, rowid ASC LIMIT ?
            """,
            (conversation_id, safe_limit),
        )
        return [self._to_message(row) for row in rows]

    def recent_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 40,
    ) -> list[MessageRecord]:
        """Newest messages in chronological order, for bounded provider context."""
        safe_limit = max(1, min(int(limit), 500))
        rows = self._db.query_all(
            """
            SELECT * FROM messages WHERE conversation_id = ?
            ORDER BY created_at DESC, rowid DESC LIMIT ?
            """,
            (conversation_id, safe_limit),
        )
        return [self._to_message(row) for row in reversed(rows)]

    def message_count(self, conversation_id: str) -> int:
        row = self._db.query_one(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        return int(row["count"]) if row else 0

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS count FROM conversations")
        return int(row["count"]) if row else 0

    def delete(self, conversation_id: str) -> bool:
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _to_conversation(row: dict[str, Any]) -> ConversationRecord:
        payload = dict(row)
        payload["archived"] = bool(payload.get("archived", 0))
        return ConversationRecord(**payload)

    @staticmethod
    def _to_message(row: dict[str, Any]) -> MessageRecord:
        payload = dict(row)
        raw_metadata = payload.pop("metadata_json", "{}")
        try:
            metadata = json.loads(raw_metadata)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return MessageRecord(**payload, metadata=metadata)


def _clean_title(title: str) -> str:
    return " ".join((title or "").split())[:80].strip()


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        title: str,
        *,
        goal: str = "",
        priority: int = 2,
        due_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        now = utc_now_iso()
        task_id = f"tsk_{uuid.uuid4().hex[:12]}"
        safe_priority = max(1, min(int(priority), 4))
        self._db.execute(
            """
            INSERT INTO tasks(id, title, goal, status, priority, created_at, updated_at, due_at, metadata_json)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                title,
                goal,
                safe_priority,
                now,
                now,
                due_at,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        return TaskRecord(
            id=task_id,
            title=title,
            goal=goal,
            status="pending",
            priority=safe_priority,
            created_at=now,
            updated_at=now,
            due_at=due_at,
            metadata=metadata or {},
        )

    def get(self, task_id: str) -> TaskRecord | None:
        row = self._db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self._to_model(row) if row else None

    def list(self, *, limit: int = 50, status: TaskStatus | None = None) -> list[TaskRecord]:
        safe_limit = max(1, min(int(limit), 500))
        if status:
            rows = self._db.query_all(
                "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, safe_limit),
            )
        else:
            rows = self._db.query_all(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (safe_limit,)
            )
        return [self._to_model(row) for row in rows]

    def set_status(self, task_id: str, status: TaskStatus) -> bool:
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now_iso(), task_id),
            )
            return cursor.rowcount > 0

    def counts_by_status(self) -> dict[str, int]:
        rows = self._db.query_all("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status")
        return {row["status"]: int(row["count"]) for row in rows}

    @staticmethod
    def _to_model(row: dict[str, Any]) -> TaskRecord:
        payload = dict(row)
        raw_metadata = payload.pop("metadata_json", "{}")
        try:
            metadata = json.loads(raw_metadata)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return TaskRecord(**payload, metadata=metadata)
