from __future__ import annotations

import asyncio
import errno

from google.genai import errors as genai_errors

from ai.errors import AIError, AIErrorKind, classify_exception

VALID_KEY = "AIza" + "q" * 32


def api_error(code: int, status: str = "ERROR") -> genai_errors.APIError:
    return genai_errors.APIError(
        code,
        {"error": {"code": code, "message": "test detail", "status": status}},
    )


def test_auth_rate_limit_and_server_errors_are_classified() -> None:
    auth = classify_exception(api_error(401, "UNAUTHENTICATED"))
    assert auth.kind is AIErrorKind.AUTH
    assert auth.retryable is False
    assert auth.status_code == 401
    assert "rejected the API key" in auth.message

    limited = classify_exception(api_error(429, "RESOURCE_EXHAUSTED"))
    assert limited.kind is AIErrorKind.RATE_LIMIT
    assert limited.retryable is True
    assert limited.status_code == 429

    server = classify_exception(api_error(503, "UNAVAILABLE"))
    assert server.kind is AIErrorKind.SERVER
    assert server.retryable is True

    invalid = classify_exception(api_error(400, "INVALID_ARGUMENT"))
    assert invalid.kind is AIErrorKind.INVALID_REQUEST
    assert invalid.retryable is False


def test_timeout_network_and_unknown_are_classified() -> None:
    timeout = classify_exception(TimeoutError("slow"))
    assert timeout.kind is AIErrorKind.TIMEOUT
    assert timeout.retryable is True

    network = classify_exception(ConnectionError("offline"))
    assert network.kind is AIErrorKind.NETWORK
    assert network.retryable is True

    oserror = classify_exception(OSError(errno.ECONNREFUSED, "refused"))
    assert oserror.kind is AIErrorKind.NETWORK

    unknown = classify_exception(RuntimeError("boom"))
    assert unknown.kind is AIErrorKind.UNKNOWN
    assert unknown.retryable is False


def test_cancellation_keeps_its_own_kind() -> None:
    error = classify_exception(asyncio.CancelledError())
    assert error.kind is AIErrorKind.CANCELLED


def test_classified_messages_redact_credentials() -> None:
    error = AIError(
        AIErrorKind.UNKNOWN,
        f"request failed with key {VALID_KEY} in the query",
    )
    assert VALID_KEY not in error.message
    assert "[REDACTED]" in error.message


def test_existing_ai_error_is_returned_unchanged() -> None:
    original = AIError(AIErrorKind.EMPTY_RESPONSE, "empty")
    assert classify_exception(original) is original
