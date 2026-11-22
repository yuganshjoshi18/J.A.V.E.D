from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from ai.errors import AIError, AIErrorKind
from ai.gemini_provider import SYSTEM_INSTRUCTION, GeminiProvider
from ai.provider import ChatTurn
from config.settings import GeminiSettings
from utils.security import ENV_VAR, SecretStore

VALID_KEY = "AIza" + "q" * 32


def api_error(code: int, status: str = "ERROR") -> genai_errors.APIError:
    return genai_errors.APIError(
        code,
        {"error": {"code": code, "message": "test detail", "status": status}},
    )


def response(text: str, finish: str = "STOP") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=finish)],
    )


class FakeStream:
    def __init__(self, items) -> None:
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeModels:
    def __init__(self, stream_script=None, content_script=None) -> None:
        self.stream_script = list(stream_script or [])
        self.content_script = list(content_script or [])
        self.stream_calls: list[dict] = []
        self.content_calls: list[dict] = []

    async def generate_content_stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        if not self.stream_script:
            raise AssertionError("unexpected streaming call")
        attempt = self.stream_script.pop(0)
        if isinstance(attempt, BaseException):
            raise attempt
        return FakeStream(attempt)

    async def generate_content(self, **kwargs):
        self.content_calls.append(kwargs)
        if not self.content_script:
            raise AssertionError("unexpected non-streaming call")
        attempt = self.content_script.pop(0)
        if isinstance(attempt, BaseException):
            raise attempt
        return attempt


@dataclass
class FakeClient:
    models: FakeModels
    closed: bool = False

    def __post_init__(self) -> None:
        self.aio = SimpleNamespace(models=self.models)

    def close(self) -> None:
        self.closed = True


def settings(**overrides) -> GeminiSettings:
    values = {
        "model": "gemini-test",
        "temperature": 0.4,
        "max_output_tokens": 256,
        "timeout_seconds": 5.0,
        "max_retries": 2,
        "streaming": True,
    }
    values.update(overrides)
    return GeminiSettings(**values)


def build_provider(tmp_path, models: FakeModels, *, configured=True, retry_delay=0.0):
    env = {ENV_VAR: VALID_KEY} if configured else {}
    secrets = SecretStore(tmp_path / "secrets", env=env)
    keys: list[str] = []
    client = FakeClient(models)

    def factory(key: str) -> FakeClient:
        keys.append(key)
        return client

    provider = GeminiProvider(
        secrets=secrets,
        settings_provider=settings,
        client_factory=factory,
        retry_base_delay=retry_delay,
    )
    return provider, client, keys


def test_streams_text_and_maps_history(tmp_path) -> None:
    models = FakeModels(
        stream_script=[[response("Hello"), response(", world"), response("!")]]
    )
    provider, client, keys = build_provider(tmp_path, models)
    deltas: list[str] = []
    history = [
        ChatTurn("user", "First question"),
        ChatTurn("assistant", "First answer"),
        ChatTurn("user", "Second question"),
    ]

    result = asyncio.run(provider.generate(history, on_delta=deltas.append))

    assert result.text == "Hello, world!"
    assert result.model == "gemini-test"
    assert result.chunks == 3
    assert result.retries == 0
    assert result.finish_reason == "STOP"
    assert deltas == ["Hello", ", world", "!"]
    assert keys == [VALID_KEY]

    call = models.stream_calls[0]
    assert call["model"] == "gemini-test"
    assert [content.role for content in call["contents"]] == ["user", "model", "user"]
    assert [content.parts[0].text for content in call["contents"]] == [
        "First question",
        "First answer",
        "Second question",
    ]
    config = call["config"]
    assert config.system_instruction == SYSTEM_INSTRUCTION
    assert config.temperature == pytest.approx(0.4)
    assert config.max_output_tokens == 256
    assert config.http_options.timeout == 5000
    assert provider.configured is True

    provider.close()
    assert client.closed is True


def test_retries_rate_limits_before_any_text(tmp_path) -> None:
    models = FakeModels(
        stream_script=[api_error(429, "RESOURCE_EXHAUSTED"), [response("recovered")]]
    )
    provider, client, keys = build_provider(tmp_path, models, retry_delay=0.0)

    result = asyncio.run(provider.generate([ChatTurn("user", "Hi")]))

    assert result.text == "recovered"
    assert result.retries == 1
    assert len(models.stream_calls) == 2
    assert keys == [VALID_KEY]
    assert client.closed is False


def test_does_not_retry_after_partial_text(tmp_path) -> None:
    models = FakeModels(
        stream_script=[[response("partial"), api_error(500, "INTERNAL")]]
    )
    provider, _client, _keys = build_provider(tmp_path, models, retry_delay=0.0)
    deltas: list[str] = []

    with pytest.raises(AIError) as caught:
        asyncio.run(provider.generate([ChatTurn("user", "Hi")], on_delta=deltas.append))

    assert caught.value.kind is AIErrorKind.SERVER
    assert deltas == ["partial"]
    assert len(models.stream_calls) == 1


def test_authentication_errors_are_not_retried(tmp_path) -> None:
    models = FakeModels(stream_script=[api_error(401, "UNAUTHENTICATED")])
    provider, _client, _keys = build_provider(tmp_path, models, retry_delay=0.0)

    with pytest.raises(AIError) as caught:
        asyncio.run(provider.generate([ChatTurn("user", "Hi")]))

    assert caught.value.kind is AIErrorKind.AUTH
    assert len(models.stream_calls) == 1


def test_empty_stream_is_reported(tmp_path) -> None:
    models = FakeModels(stream_script=[[]])
    provider, _client, _keys = build_provider(tmp_path, models, retry_delay=0.0)

    with pytest.raises(AIError) as caught:
        asyncio.run(provider.generate([ChatTurn("user", "Hi")]))

    assert caught.value.kind is AIErrorKind.EMPTY_RESPONSE


def test_non_streaming_mode_uses_generate_content(tmp_path) -> None:
    models = FakeModels(content_script=[response("single reply")])

    def non_streaming() -> GeminiSettings:
        return settings(streaming=False)

    provider = GeminiProvider(
        secrets=SecretStore(tmp_path / "secrets", env={ENV_VAR: VALID_KEY}),
        settings_provider=non_streaming,
        client_factory=lambda key: FakeClient(models),
        retry_base_delay=0.0,
    )
    deltas: list[str] = []

    result = asyncio.run(provider.generate([ChatTurn("user", "Hi")], on_delta=deltas.append))

    assert result.text == "single reply"
    assert deltas == ["single reply"]
    assert models.stream_calls == []
    assert len(models.content_calls) == 1


def test_missing_key_is_not_configured_and_never_builds_a_client(tmp_path) -> None:
    models = FakeModels()
    provider, _client, keys = build_provider(tmp_path, models, configured=False)

    assert provider.configured is False
    with pytest.raises(AIError) as caught:
        asyncio.run(provider.generate([ChatTurn("user", "Hi")]))

    assert caught.value.kind is AIErrorKind.NOT_CONFIGURED
    assert keys == []
    assert models.stream_calls == []


def test_timeout_is_classified(tmp_path) -> None:
    models = FakeModels(stream_script=[TimeoutError("slow")])
    provider = GeminiProvider(
        secrets=SecretStore(tmp_path / "secrets", env={ENV_VAR: VALID_KEY}),
        settings_provider=lambda: settings(max_retries=0),
        client_factory=lambda key: FakeClient(models),
        retry_base_delay=0.0,
    )

    with pytest.raises(AIError) as caught:
        asyncio.run(provider.generate([ChatTurn("user", "Hi")]))

    assert caught.value.kind is AIErrorKind.TIMEOUT
    assert len(models.stream_calls) == 1
