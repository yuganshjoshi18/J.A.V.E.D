from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from ai.errors import AIError, AIErrorKind
from ai.provider import ProviderResult
from core.audit import AuditService
from core.event_manager import EventBus
from core.services.chat import ChatBusyError, ChatService
from core.task_manager import TaskManager
from memory.database import Database
from memory.repositories import AuditRepository, ConversationRepository


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        *,
        chunks: tuple[str, ...] = ("Hel", "lo"),
        configured: bool = True,
        error: BaseException | None = None,
        pause_at: str | None = None,
    ) -> None:
        self.chunks = chunks
        self.configured = configured
        self.error = error
        self.pause_at = pause_at
        self.history: list = []
        self.entered = threading.Event()
        self._pause_event: asyncio.Event | None = None

    def describe(self) -> str:
        return "fake-model · streaming"

    async def generate(self, history, *, on_delta=None):
        self.history = list(history)
        if self.pause_at == "before":
            await self._pause()
        for chunk in self.chunks:
            if on_delta is not None:
                on_delta(chunk)
        if self.pause_at == "after":
            await self._pause()
        if self.error is not None:
            raise self.error
        return ProviderResult(
            text="".join(self.chunks),
            model="fake-model",
            chunks=len(self.chunks),
        )

    async def _pause(self) -> None:
        self._pause_event = asyncio.Event()
        self.entered.set()
        await self._pause_event.wait()


def wait_for(predicate, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before the timeout")


@pytest.fixture
def chat_env(async_runtime, app_paths, settings_manager):
    database = Database(app_paths.database_file)
    database.connect()
    bus = EventBus()
    repository = ConversationRepository(database)
    audit = AuditService(AuditRepository(database), bus)
    tasks = TaskManager(async_runtime.loop, bus)
    providers: list[FakeProvider] = []

    def build(provider: FakeProvider | None = None) -> ChatService:
        active = provider or FakeProvider()
        providers.append(active)
        return ChatService(
            conversations=repository,
            provider=active,
            tasks=tasks,
            bus=bus,
            audit=audit,
            settings_provider=settings_manager.load,
        )

    try:
        yield SimpleNamespace(
            db=database,
            bus=bus,
            repository=repository,
            audit=audit,
            tasks=tasks,
            runtime=async_runtime,
            build=build,
            providers=providers,
        )
    finally:
        tasks.cancel_all()
        database.close()


def test_send_persists_turns_and_emits_events(chat_env) -> None:
    provider = FakeProvider()
    service = chat_env.build(provider)
    events: list[tuple[str, dict]] = []
    for event_type in (
        "chat.message_added",
        "chat.started",
        "chat.delta",
        "chat.completed",
        "chat.conversations_changed",
    ):
        chat_env.bus.subscribe(
            event_type,
            lambda event, name=event_type: events.append((name, dict(event.payload))),
        )

    handle = service.send(None, "Hello there")
    wait_for(
        lambda: (chat_env.tasks.get(handle.task_id) or {}).get("status") == "completed"
    )
    wait_for(lambda: chat_env.repository.message_count(handle.conversation.id) == 2)

    conversation = chat_env.repository.get(handle.conversation.id)
    assert conversation is not None
    assert conversation.title == "Hello there"

    messages = chat_env.repository.messages(handle.conversation.id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == "Hello there"
    assert messages[1].content == "Hello"
    assert messages[1].metadata["model"] == "fake-model"
    assert [turn.role for turn in provider.history] == ["user"]

    names = [name for name, _payload in events]
    assert names.index("chat.message_added") < names.index("chat.started")
    assert names.index("chat.started") < names.index("chat.delta")
    assert names[-1] == "chat.conversations_changed"
    deltas = "".join(payload["text"] for name, payload in events if name == "chat.delta")
    assert deltas == "Hello"
    completed = [payload for name, payload in events if name == "chat.completed"][0]
    assert completed["message"]["content"] == "Hello"

    actions = [entry["action"] for entry in chat_env.audit.recent(20)]
    assert "message_sent" in actions
    assert "reply_received" in actions
    assert service.is_busy(handle.conversation.id) is False


def test_second_send_is_rejected_while_busy(chat_env) -> None:
    provider = FakeProvider(chunks=(), pause_at="before")
    service = chat_env.build(provider)
    handle = service.send(None, "First")
    assert provider.entered.wait(5.0)

    with pytest.raises(ChatBusyError):
        service.send(handle.conversation.id, "Second")
    with pytest.raises(ChatBusyError):
        service.delete_conversation(handle.conversation.id)

    assert service.cancel(handle.conversation.id) is True
    wait_for(
        lambda: (chat_env.tasks.get(handle.task_id) or {}).get("status") == "cancelled"
    )
    wait_for(lambda: not service.is_busy(handle.conversation.id))
    # Nothing was generated, so only the user message is stored.
    assert chat_env.repository.message_count(handle.conversation.id) == 1


def test_cancellation_persists_partial_reply(chat_env) -> None:
    provider = FakeProvider(chunks=("part",), pause_at="after")
    service = chat_env.build(provider)
    cancelled: list[dict] = []
    chat_env.bus.subscribe("chat.cancelled", lambda event: cancelled.append(dict(event.payload)))

    handle = service.send(None, "Write something")
    wait_for(lambda: cancelled or provider.entered.is_set())
    assert provider.entered.wait(5.0)
    assert service.cancel(handle.conversation.id) is True
    wait_for(
        lambda: (chat_env.tasks.get(handle.task_id) or {}).get("status") == "cancelled"
    )
    wait_for(lambda: chat_env.repository.message_count(handle.conversation.id) == 2)

    messages = chat_env.repository.messages(handle.conversation.id)
    partial = messages[-1]
    assert partial.role == "assistant"
    assert partial.content == "part"
    assert partial.metadata["interrupted"] is True
    assert partial.metadata["reason"] == "cancelled"
    wait_for(lambda: bool(cancelled))
    assert cancelled[0]["partial"] == "part"


def test_failure_is_classified_and_partial_text_is_kept(chat_env) -> None:
    provider = FakeProvider(
        chunks=("partial ", "text"),
        error=AIError(AIErrorKind.RATE_LIMIT, "Rate limited. Try later."),
    )
    service = chat_env.build(provider)
    failures: list[dict] = []
    chat_env.bus.subscribe("chat.failed", lambda event: failures.append(dict(event.payload)))

    handle = service.send(None, "Hello")
    wait_for(lambda: bool(failures))
    wait_for(lambda: chat_env.repository.message_count(handle.conversation.id) == 2)

    assert failures[0]["kind"] == "rate_limit"
    assert failures[0]["partial"] == "partial text"
    messages = chat_env.repository.messages(handle.conversation.id)
    assert messages[-1].content == "partial text"
    assert messages[-1].metadata["reason"] == "rate_limit"
    failed_audit = [
        entry
        for entry in chat_env.audit.recent(20)
        if entry["action"] == "reply_failed"
    ]
    assert failed_audit and failed_audit[0]["success"] is False


def test_unconfigured_provider_refuses_before_persisting(chat_env) -> None:
    service = chat_env.build(FakeProvider(configured=False))

    with pytest.raises(AIError) as caught:
        service.send(None, "Hello")

    assert caught.value.kind is AIErrorKind.NOT_CONFIGURED
    assert chat_env.repository.count() == 0
    assert service.is_busy() is False


def test_create_rename_and_delete_conversation(chat_env) -> None:
    service = chat_env.build(FakeProvider())
    conversation = service.create_conversation("Initial")

    assert service.rename_conversation(conversation.id, "Renamed") is True
    assert service.get_conversation(conversation.id).title == "Renamed"
    assert service.delete_conversation(conversation.id) is True
    assert service.get_conversation(conversation.id) is None
