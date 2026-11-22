"""Gemini adapter built on the official Google GenAI SDK.

The adapter owns vendor specifics only: message mapping, request configuration,
streaming, timeout and retry. It never persists conversation state and never
reads the API key from settings — the key comes from :class:`SecretStore`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Sequence

from ai.errors import AIError, AIErrorKind, classify_exception
from ai.provider import ChatTurn, ProviderResult
from config.settings import GeminiSettings
from utils.logger import get_logger
from utils.security import SecretStore

log = get_logger("ai.gemini")

SYSTEM_INSTRUCTION = (
    "You are J.A.V.E.D., a personal AI assistant running on the user's Windows computer. "
    "Be direct, accurate and useful. State uncertainty instead of inventing facts. "
    "You cannot control the computer, run tools, read files, or listen to audio yet; "
    "if asked, say that capability is not implemented. Never claim an action you did not take."
)

# Retry delays intentionally stay short: the user is waiting in a chat window.
_RETRY_BASE_SECONDS = 0.8
_RETRY_MAX_SECONDS = 4.0


class GeminiProvider:
    """Streaming Gemini client with bounded retries and classified errors."""

    name = "gemini"

    def __init__(
        self,
        *,
        secrets: SecretStore,
        settings_provider: Callable[[], GeminiSettings],
        client_factory: Callable[[str], Any] | None = None,
        retry_base_delay: float = _RETRY_BASE_SECONDS,
    ) -> None:
        self._secrets = secrets
        self._settings_provider = settings_provider
        self._client_factory = client_factory
        self._retry_base_delay = max(0.0, retry_base_delay)
        self._client: Any | None = None
        self._client_key: str | None = None

    # ------------------------------------------------------------- status
    @property
    def configured(self) -> bool:
        try:
            key, _source = self._secrets.get_api_key()
        except Exception:
            log.debug("Could not read the secret store while checking readiness.", exc_info=True)
            return False
        return bool(key)

    def describe(self) -> str:
        settings = self._settings_provider()
        if not self.configured:
            return "No Gemini API key configured."
        mode = "streaming" if settings.streaming else "single response"
        return (
            f"{settings.model} · {mode} · timeout {settings.timeout_seconds:.0f}s "
            f"· retries {settings.max_retries}"
        )

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        client, self._client, self._client_key = self._client, None, None
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.debug("Gemini client close failed.", exc_info=True)

    # ------------------------------------------------------------- requests
    async def generate(
        self,
        history: Sequence[ChatTurn],
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> ProviderResult:
        settings = self._settings_provider()
        key, _source = self._secrets.get_api_key()
        if not key:
            raise AIError(
                AIErrorKind.NOT_CONFIGURED,
                "No Gemini API key is configured. Add one in Settings or set GEMINI_API_KEY.",
            )

        client = self._client_for(key)
        contents = self._contents(history)
        config = self._config(settings)
        attempts = settings.max_retries + 1
        last_error: AIError | None = None

        for attempt in range(attempts):
            started = time.monotonic()
            chunks = 0
            pieces: list[str] = []
            finish_reason: str | None = None
            try:
                async with asyncio.timeout(settings.timeout_seconds):
                    if settings.streaming:
                        stream = await client.aio.models.generate_content_stream(
                            model=settings.model,
                            contents=contents,
                            config=config,
                        )
                        async for response in stream:
                            finish_reason = self._finish_reason(response) or finish_reason
                            delta = self._response_text(response)
                            if not delta:
                                continue
                            pieces.append(delta)
                            chunks += 1
                            if on_delta is not None:
                                on_delta(delta)
                    else:
                        response = await client.aio.models.generate_content(
                            model=settings.model,
                            contents=contents,
                            config=config,
                        )
                        finish_reason = self._finish_reason(response)
                        delta = self._response_text(response)
                        if delta:
                            pieces.append(delta)
                            chunks = 1
                            if on_delta is not None:
                                on_delta(delta)

                text = "".join(pieces).strip()
                if not text:
                    raise AIError(
                        AIErrorKind.EMPTY_RESPONSE,
                        "Gemini returned an empty response. Try rephrasing the message.",
                    )
                log.info(
                    "Gemini reply received (model=%s, chunks=%s, retries=%s, %.2fs).",
                    settings.model,
                    chunks,
                    attempt,
                    time.monotonic() - started,
                )
                return ProviderResult(
                    text=text,
                    model=settings.model,
                    chunks=chunks,
                    retries=attempt,
                    finish_reason=finish_reason,
                )
            except asyncio.CancelledError:
                raise
            except AIError:
                raise
            except Exception as exc:
                error = classify_exception(exc)
                last_error = error
                # Never retry after text has reached the UI: a retry would
                # duplicate a partial answer.
                if not error.retryable or pieces or attempt >= attempts - 1:
                    raise error from exc
                delay = min(
                    _RETRY_MAX_SECONDS,
                    self._retry_base_delay * (2**attempt),
                )
                log.warning(
                    "Gemini request failed (%s); retrying in %.1fs (attempt %s/%s).",
                    error.kind.value,
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)

        raise last_error or AIError(AIErrorKind.UNKNOWN, "Gemini request failed.")

    # ------------------------------------------------------------- helpers
    def _client_for(self, key: str) -> Any:
        if self._client is not None and self._client_key == key:
            return self._client
        self.close()
        if self._client_factory is not None:
            self._client = self._client_factory(key)
        else:
            from google import genai

            self._client = genai.Client(api_key=key)
        self._client_key = key
        return self._client

    @staticmethod
    def _contents(history: Sequence[ChatTurn]) -> list[Any]:
        from google.genai import types

        contents: list[Any] = []
        for turn in history:
            if not turn.content.strip():
                continue
            role = "model" if turn.role == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=turn.content)],
                )
            )
        return contents

    @staticmethod
    def _config(settings: GeminiSettings) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            http_options=types.HttpOptions(timeout=int(settings.timeout_seconds * 1000)),
        )

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            return response.text or ""
        except Exception:
            # Usage-only and blocked chunks can have no text; they are not errors.
            return ""

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            return None
        return getattr(reason, "value", None) or str(reason)
