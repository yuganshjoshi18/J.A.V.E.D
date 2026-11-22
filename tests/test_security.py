from __future__ import annotations

import sys

import pytest

from utils.security import (
    ENV_VAR,
    SecretStore,
    fingerprint,
    protect_secret,
    unprotect_secret,
    validate_api_key,
)

pytestmark = pytest.mark.windows

VALID_KEY = "AIza" + "b" * 32


def test_validate_api_key_normalises_whitespace() -> None:
    assert validate_api_key(f"  {VALID_KEY}  ") == VALID_KEY


@pytest.mark.parametrize(
    "value",
    ["", "   ", "your-key", "changeme", "short-key", "key with spaces " + "x" * 20],
)
def test_validate_api_key_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_api_key(value)


def test_fingerprint_is_stable_and_non_reversible() -> None:
    first = fingerprint(VALID_KEY)
    second = fingerprint(VALID_KEY)

    assert first == second
    assert len(first) == 12
    assert VALID_KEY not in first


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_round_trip() -> None:
    ciphertext = protect_secret(b"hello javed")

    assert ciphertext != b"hello javed"
    assert unprotect_secret(ciphertext) == b"hello javed"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_secret_store_round_trip_and_delete(app_paths, monkeypatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    store = SecretStore(app_paths.secrets_dir, env={})

    status = store.set_api_key(VALID_KEY)
    assert status.configured is True
    assert status.source == "dpapi"
    assert status.storage == "Windows DPAPI"
    assert status.fingerprint == fingerprint(VALID_KEY)

    key, source = store.get_api_key()
    assert key == VALID_KEY
    assert source == "dpapi"
    assert VALID_KEY.encode() not in store.key_file.read_bytes()

    assert store.delete_api_key() is True
    assert store.get_api_key() == (None, "none")
    assert store.delete_api_key() is False


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_environment_key_takes_precedence(app_paths) -> None:
    store = SecretStore(app_paths.secrets_dir, env={ENV_VAR: f"  {VALID_KEY}  "})

    key, source = store.get_api_key()

    assert key == VALID_KEY
    assert source == "environment"
    assert store.status().storage == "Environment variable"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_corrupt_secret_file_is_reported_as_not_configured(app_paths) -> None:
    store = SecretStore(app_paths.secrets_dir, env={})
    app_paths.secrets_dir.mkdir(parents=True, exist_ok=True)
    store.key_file.write_bytes(b"not a valid DPAPI blob")

    assert store.get_api_key() == (None, "none")
    assert store.status().configured is False
