"""Conversation orchestration: persistence, streaming, cancellation and audit.

The service runs provider calls on the dedicated asyncio loop through the task
manager, emits thread-safe events for the Qt bridge, and stores every completed
turn locally. Message content is never written to the audit trail.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from ai.errors import AIError, AIErrorKind, classify_exception
from ai.provider import ChatProvider, ChatTurn
from config.settings import AppSettings
from core.audit import AuditService
from core.event_manager import EventBus
from core.task_manager import TaskManager
from memory.models import ConversationRecord, MessageRecord
from memory.repositories import ConversationRepository
from utils.logger import get_logger

log = get_logger("chat")

DEFAULT_HISTORY_LIMIT = 40
MAX_MESSAGE_CHARS = 12000


class ChatBusyError(RuntimeError):
    """Raised when a conversation already has a reply in flight."""


@dataclass(frozen=True)
class ChatTurnHandle:
    conversation: ConversationRecord
    user_message: MessageRecord
    task_id: str
    model: str


@dataclass
class _ActiveTurn:
    token: str
    task_id: str | None = None
    cancel_requested: bool = False


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        provider: ChatProvider,
        tasks: TaskManager,
        bus: EventBus,
        audit: AuditService,
        settings_provider: Callable[[], AppSettings],
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        max_message_chars: int = MAX_MESSAGE_CHARS,
    ) -> None:
        self._conversations = conversations
        self._provider = provider
        self._tasks = tasks
        self._bus = bus
        self._audit = audit
        self._settings_provider = settings_provider
        self._history_limit = max(1, min(int(history_limit), 200))
        self._max_message_chars = max(1, int(max_message_chars))
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveTurn] = {}

    # --------------------------------------------------------------- status
    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "name", "provider")

    @property
    def configured(self) -> bool:
        return bool(getattr(self._provider, "configured", False))

    @property
    def model(self) -> str:
        return self._settings_provider().gemini.model

    def describe(self) -> str:
        describe = getattr(self._provider, "describe", None)
        if callable(describe):
            return str(describe())
        return self.model

    def is_busy(self, conversation_id: str | None = None) -> bool:
        with self._lock:
            if conversation_id is None:
                return bool(self._active)
            return conversation_id in self._active

    # ---------------------------------------------------------- conversations
    def create_conversation(self, title: str = "New conversation") -> ConversationRecord:
        conversation = self._conversations.create(title)
        self._bus.emit(
            "chat.conversations_changed",
            source="chat",
            conversation_id=conversation.id,
        )
        return conversation

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    def list_conversations(self, limit: int = 50) -> list[ConversationRecord]:
        return self._conversations.list(limit=limit)

    def messages(self, conversation_id: str, limit: int = 200) -> list[MessageRecord]:
        return self._conversations.messages(conversation_id, limit=limit)

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        renamed = self._conversations.rename(conversation_id, title)
        if renamed:
            self._bus.emit(
                "chat.conversations_changed",
                source="chat",
                conversation_id=conversation_id,
            )
        return renamed

    def delete_conversation(self, conversation_id: str) -> bool:
        if self.is_busy(conversation_id):
            raise ChatBusyError("Stop the active reply before deleting this conversation.")
        deleted = self._conversations.delete(conversation_id)
        if deleted:
            self._audit.record(
                "chat",
                "conversation_deleted",
                detail={"conversation_id": conversation_id},
                actor="user",
            )
            self._bus.emit(
                "chat.conversations_changed",
                source="chat",
                conversation_id=conversation_id,
                deleted=True,
            )
        return deleted

    # ------------------------------------------------------------------ turns
    def send(self, conversation_id: str | None, text: str) -> ChatTurnHandle:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Message must not be empty.")
        if len(cleaned) > self._max_message_chars:
            raise ValueError(
                f"Message is too long ({len(cleaned)} characters; limit "
                f"{self._max_message_chars})."
            )
        if not self.configured:
            raise AIError(
                AIErrorKind.NOT_CONFIGURED,
                "No Gemini API key is configured. Add one in Settings or set GEMINI_API_KEY.",
            )

        settings = self._settings_provider()
        conversation = (
            self._conversations.get(conversation_id) if conversation_id else None
        )
        if conversation is None:
            conversation = self._conversations.create(_title_from_text(cleaned))
        elif (
            conversation.title == "New conversation"
            and self._conversations.message_count(conversation.id) == 0
        ):
            self._conversations.rename(conversation.id, _title_from_text(cleaned))
            conversation = self._conversations.get(conversation.id) or conversation

        with self._lock:
            if conversation.id in self._active:
                raise ChatBusyError("A reply is already being generated.")

        user_message = self._conversations.add_message(
            conversation.id,
            "user",
            cleaned,
        )
        self._audit.record(
            "chat",
            "message_sent",
            detail={
                "conversation_id": conversation.id,
                "characters": len(cleaned),
                "model": settings.gemini.model,
            },
            actor="user",
        )
        self._bus.emit(
            "chat.message_added",
            source="chat",
            conversation_id=conversation.id,
            message=user_message.model_dump(mode="json"),
        )

        token = uuid.uuid4().hex
        state = _ActiveTurn(token=token)
        with self._lock:
            self._active[conversation.id] = state

        self._bus.emit(
            "chat.started",
            source="chat",
            conversation_id=conversation.id,
            model=settings.gemini.model,
            provider=self.provider_name,
        )
        try:
            task_id = self._tasks.start(
                "chat_reply",
                lambda: self._run_turn(conversation.id, state),
                metadata={"conversation_id": conversation.id},
            )
        except Exception:
            with self._lock:
                self._active.pop(conversation.id, None)
            raise

        cancel_now = False
        with self._lock:
            if self._active.get(conversation.id) is state:
                state.task_id = task_id
                cancel_now = state.cancel_requested
        if cancel_now:
            self._tasks.cancel(task_id)

        return ChatTurnHandle(
            conversation=conversation,
            user_message=user_message,
            task_id=task_id,
            model=settings.gemini.model,
        )

    def cancel(self, conversation_id: str) -> bool:
        with self._lock:
            state = self._active.get(conversation_id)
            if state is None:
                return False
            state.cancel_requested = True
            task_id = state.task_id
        if task_id is None:
            return True
        return self._tasks.cancel(task_id)

    def cancel_all(self) -> int:
        with self._lock:
            ids = list(self._active)
        return sum(1 for conversation_id in ids if self.cancel(conversation_id))

    # -------------------------------------------------------------- internals
    async def _run_turn(self, conversation_id: str, state: _ActiveTurn) -> None:
        started = time.monotonic()
        partial: list[str] = []

        def on_delta(delta: str) -> None:
            if not delta:
                return
            partial.append(delta)
            self._bus.emit(
                "chat.delta",
                source="chat",
                conversation_id=conversation_id,
                text=delta,
            )

        try:
            history = self._conversations.recent_messages(
                conversation_id, limit=self._history_limit
            )
            turns = [ChatTurn(role=item.role, content=item.content) for item in history]
            result = await self._provider.generate(turns, on_delta=on_delta)
        except asyncio.CancelledError:
            partial_text = "".join(partial).strip()
            message = self._store_interrupted(
                conversation_id, partial_text, "cancelled"
            )
            self._audit.record(
                "chat",
                "reply_cancelled",
                detail={
                    "conversation_id": conversation_id,
                    "characters": len(partial_text),
                },
                actor="user",
            )
            self._bus.emit(
                "chat.cancelled",
                source="chat",
                conversation_id=conversation_id,
                partial=partial_text,
                message=message.model_dump(mode="json") if message else None,
            )
            raise
        except AIError as exc:
            self._fail(conversation_id, exc, partial, started)
            return
        except Exception as exc:  # defensive: provider adapters classify their own errors
            self._fail(conversation_id, classify_exception(exc), partial, started)
            return
        else:
            message = self._conversations.add_message(
                conversation_id,
                "assistant",
                result.text,
                metadata={
                    "provider": self.provider_name,
                    "model": result.model,
                    "chunks": result.chunks,
                    "retries": result.retries,
                    "finish_reason": result.finish_reason,
                },
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self._audit.record(
                "chat",
                "reply_received",
                detail={
                    "conversation_id": conversation_id,
                    "provider": self.provider_name,
                    "model": result.model,
                    "chunks": result.chunks,
                    "retries": result.retries,
                    "characters": len(result.text),
                    "elapsed_ms": elapsed_ms,
                },
            )
            self._bus.emit(
                "chat.completed",
                source="chat",
                conversation_id=conversation_id,
                message=message.model_dump(mode="json"),
                model=result.model,
                chunks=result.chunks,
                retries=result.retries,
                elapsed_ms=elapsed_ms,
            )
        finally:
            with self._lock:
                if self._active.get(conversation_id) is state:
                    self._active.pop(conversation_id, None)
            self._bus.emit(
                "chat.conversations_changed",
                source="chat",
                conversation_id=conversation_id,
            )

    def _store_interrupted(
        self,
        conversation_id: str,
        partial_text: str,
        reason: str,
    ) -> MessageRecord | None:
        if not partial_text:
            return None
        try:
            return self._conversations.add_message(
                conversation_id,
                "assistant",
                partial_text,
                metadata={"interrupted": True, "reason": reason},
            )
        except Exception:
            log.exception("Could not persist an interrupted reply.")
            return None

    def _fail(
        self,
        conversation_id: str,
        error: AIError,
        partial: list[str],
        started: float,
    ) -> None:
        partial_text = "".join(partial).strip()
        message = self._store_interrupted(conversation_id, partial_text, error.kind.value)
        self._audit.record(
            "chat",
            "reply_failed",
            detail={
                "conversation_id": conversation_id,
                "kind": error.kind.value,
                "status_code": error.status_code,
                "retryable": error.retryable,
                "characters": len(partial_text),
            },
            actor="system",
            success=False,
        )
        self._bus.emit(
            "chat.failed",
            source="chat",
            conversation_id=conversation_id,
            kind=error.kind.value,
            error=error.message,
            status_code=error.status_code,
            retryable=error.retryable,
            partial=partial_text,
            message=message.model_dump(mode="json") if message else None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def _title_from_text(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 60:
        return compact
    return compact[:57].rstrip() + "…"
