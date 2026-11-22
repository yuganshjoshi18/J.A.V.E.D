"""Provider-independent error classification.

Vendor exceptions are translated here so the conversation service can decide
whether to retry, what to show the user, and which condition to audit. Only
messages that are safe to display are retained; API keys never appear in them.
"""

from __future__ import annotations

import asyncio
from enum import Enum

from utils.logger import redact_text


class AIErrorKind(str, Enum):
    NOT_CONFIGURED = "not_configured"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    EMPTY_RESPONSE = "empty_response"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


_RETRYABLE = {
    AIErrorKind.RATE_LIMIT,
    AIErrorKind.TIMEOUT,
    AIErrorKind.NETWORK,
    AIErrorKind.SERVER,
}


class AIError(RuntimeError):
    """A classified provider failure with a user-safe description."""

    def __init__(
        self,
        kind: AIErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(redact_text(message))
        self.kind = kind
        self.message = redact_text(message)
        self.status_code = status_code
        self.retryable = kind in _RETRYABLE if retryable is None else retryable

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def _api_error_kind(code: int) -> tuple[AIErrorKind, str]:
    if code in (401, 403):
        return (
            AIErrorKind.AUTH,
            "Gemini rejected the API key. Check the key in Settings.",
        )
    if code == 429:
        return (
            AIErrorKind.RATE_LIMIT,
            "Gemini rate limit reached. Wait a moment and try again.",
        )
    if code in (400, 404, 422):
        return (
            AIErrorKind.INVALID_REQUEST,
            f"Gemini rejected the request (HTTP {code}). Check the configured model and settings.",
        )
    if code >= 500:
        return (
            AIErrorKind.SERVER,
            f"Gemini reported a server error (HTTP {code}).",
        )
    return (
        AIErrorKind.UNKNOWN,
        f"Gemini request failed (HTTP {code}).",
    )


def classify_exception(exc: BaseException) -> AIError:
    """Map a vendor, network or timeout exception to an :class:`AIError`."""
    if isinstance(exc, AIError):
        return exc

    if isinstance(exc, (asyncio.CancelledError,)):
        return AIError(AIErrorKind.CANCELLED, "Request cancelled.")

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return AIError(
            AIErrorKind.TIMEOUT,
            "Gemini did not respond within the configured timeout.",
        )

    try:
        from google.genai import errors as genai_errors
    except ImportError:  # pragma: no cover - dependency is required at runtime
        genai_errors = None

    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        kind, message = _api_error_kind(code)
        return AIError(kind, message, status_code=code or None)

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx ships with google-genai
        httpx = None

    if httpx is not None:
        if isinstance(exc, httpx.TimeoutException):
            return AIError(
                AIErrorKind.TIMEOUT,
                "Gemini did not respond within the configured timeout.",
            )
        if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.WriteError)):
            return AIError(
                AIErrorKind.NETWORK,
                "Could not reach Gemini. Check the network connection.",
            )

    if isinstance(exc, (ConnectionError, OSError)):
        return AIError(
            AIErrorKind.NETWORK,
            "Could not reach Gemini. Check the network connection.",
        )

    return AIError(
        AIErrorKind.UNKNOWN,
        f"Gemini request failed ({type(exc).__name__}).",
    )
