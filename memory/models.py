"""Validated persistence models shared by storage, agents and UI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal[
    "pending",
    "running",
    "blocked",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    timestamp: str
    category: str
    action: str
    actor: str = "system"
    detail: str = ""
    success: bool = True


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    goal: str = ""
    status: TaskStatus = "pending"
    priority: int = Field(default=2, ge=1, le=4)
    created_at: str
    updated_at: str
    due_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    created_at: str
    updated_at: str
    archived: bool = False


class MessageRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    token_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    category: str
    content: str
    source: str = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str
    updated_at: str
    expires_at: str | None = None
