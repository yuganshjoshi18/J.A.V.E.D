from __future__ import annotations

import time

import pytest

from ai.provider import ProviderResult
from core.application import ApplicationContext
from core.services.chat import ChatService
from ui.chat_widget import ChatWidget, MessageBubble
from ui.event_bridge import EventBridge
from ui.main_window import MainWindow

pytestmark = pytest.mark.ui


class FakeProvider:
    name = "fake"

    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.history: list = []

    def describe(self) -> str:
        return "fake-model · streaming · timeout 5s · retries 0"

    async def generate(self, history, *, on_delta=None):
        self.history = list(history)
        for chunk in ("Hello", " from ", "the fake provider."):
            if on_delta is not None:
                on_delta(chunk)
        return ProviderResult(
            text="Hello from the fake provider.",
            model="fake-model",
            chunks=3,
        )


def wait_until(qapp, predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def build_context(app_paths, provider: FakeProvider):
    context = ApplicationContext.create(app_paths)
    context.chat = ChatService(
        conversations=context.conversation_repository,
        provider=provider,
        tasks=context.tasks,
        bus=context.bus,
        audit=context.audit,
        settings_provider=context.settings_manager.load,
    )
    return context


def test_chat_page_streams_and_persists(qapp, app_paths) -> None:
    provider = FakeProvider()
    context = build_context(app_paths, provider)
    context.start()
    bridge = EventBridge(context.bus)
    window = MainWindow(context, bridge)
    window.show()
    qapp.processEvents()

    try:
        window.go_to("chat")
        page = window.chat_page
        assert isinstance(page, ChatWidget)
        assert page.provider_pill.property("tone") == "ok"
        assert page.send_button.isEnabled() is True

        page.composer.setPlainText("Hello there")
        page._send()

        assert wait_until(
            qapp,
            lambda: not page._streaming
            and page.history_list.count() == 1
            and page.title_label.text() == "Hello there",
        )

        messages = context.chat.messages(page._conversation_id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == "Hello there"
        assert messages[1].content == "Hello from the fake provider."

        bubbles = page.findChildren(MessageBubble)
        rendered = "\n".join(bubble.text for bubble in bubbles)
        assert "Hello there" in rendered
        assert "Hello from the fake provider." in rendered
        assert page.state_pill.property("tone") == "ok"
        assert page.stop_button.isEnabled() is False
        assert page.send_button.isEnabled() is True
        assert page.history_list.item(0).text() == "Hello there"
        assert "fake-model" in page.model_label.text()

        # A second conversation can be started without losing the first.
        page._new_chat()
        assert page.title_label.text() == "New conversation"
        assert page.history_list.count() == 1
    finally:
        window.close()
        qapp.processEvents()
        bridge.close()
        context.shutdown()


def test_chat_page_is_honest_without_a_key(qapp, app_paths) -> None:
    context = build_context(app_paths, FakeProvider(configured=False))
    context.start()
    bridge = EventBridge(context.bus)
    window = MainWindow(context, bridge)
    window.show()
    qapp.processEvents()

    try:
        window.go_to("chat")
        page = window.chat_page
        assert page.provider_pill.property("tone") == "warning"
        assert page.send_button.isEnabled() is False
        assert page.composer.isEnabled() is False
        assert "not configured" in page.empty_headline.text().lower()

        page.composer.setPlainText("This must not be sent")
        page._send()
        qapp.processEvents()

        assert page.history_list.count() == 0
        assert context.conversation_repository.count() == 0
        notices = [
            bubble.text
            for bubble in page.findChildren(MessageBubble)
            if bubble.property("role") == "system"
        ]
        assert any("No Gemini API key" in text for text in notices)
    finally:
        window.close()
        qapp.processEvents()
        bridge.close()
        context.shutdown()
