"""Secure secret storage using Windows DPAPI.

Gemini API keys are never written to settings JSON, the SQLite database or
logs. The environment variable ``GEMINI_API_KEY`` takes precedence; otherwise
the key is encrypted with the current Windows user's DPAPI key and stored under
the private application-data directory.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger

log = get_logger("security")

ENV_VAR = "GEMINI_API_KEY"
_ENTROPY = b"J.A.V.E.D/v1/gemini"
_DESCRIPTION = "J.A.V.E.D. Gemini API key"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_PLACEHOLDERS = {"", "your-key", "your_api_key", "changeme", "api-key", "none", "null"}


class SecretStorageError(RuntimeError):
    """Raised when a secret cannot be stored or retrieved safely."""


class SecretStorageUnavailable(SecretStorageError):
    """Raised when DPAPI is unavailable (for example, on non-Windows hosts)."""


@dataclass(frozen=True)
class SecretStatus:
    configured: bool
    source: str  # "environment" | "dpapi" | "none"
    storage: str  # human-readable backend label
    fingerprint: str | None


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data, max(1, len(data)))
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    return _DATA_BLOB(len(data), pointer), buffer


def _require_windows() -> None:
    if sys.platform != "win32":
        raise SecretStorageUnavailable(
            "Windows DPAPI is unavailable on this platform. "
            "Use the GEMINI_API_KEY environment variable instead."
        )


def protect_secret(plaintext: bytes, entropy: bytes = _ENTROPY) -> bytes:
    """Encrypt bytes for the current Windows user via DPAPI."""
    _require_windows()
    data_in, _data_buffer = _blob(plaintext)
    entropy_in, _entropy_buffer = _blob(entropy)
    data_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    result = crypt32.CryptProtectData(
        ctypes.byref(data_in),
        _DESCRIPTION,
        ctypes.byref(entropy_in),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not result:
        raise SecretStorageError("Windows DPAPI encryption failed.")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(data_out.pbData)


def unprotect_secret(ciphertext: bytes, entropy: bytes = _ENTROPY) -> bytes:
    """Decrypt DPAPI bytes belonging to the current Windows user."""
    _require_windows()
    data_in, _data_buffer = _blob(ciphertext)
    entropy_in, _entropy_buffer = _blob(entropy)
    data_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    result = crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy_in),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not result:
        raise SecretStorageError(
            "Windows DPAPI could not decrypt the stored key. It may belong to "
            "another Windows user or machine."
        )
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(data_out.pbData)


def _clean_env_key(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().strip('"').strip("'").strip()


def validate_api_key(value: str) -> str:
    """Normalise and sanity-check a Gemini API key without revealing it."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("API key is empty.")
    if cleaned.lower() in _PLACEHOLDERS:
        raise ValueError("That value is a placeholder, not an API key.")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("API key must not contain whitespace.")
    if len(cleaned) < 20:
        raise ValueError("API key is too short to be valid.")
    return cleaned


def fingerprint(value: str) -> str:
    """Stable, non-reversible identifier that is safe to display."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class SecretStore:
    """DPAPI-backed store for the Gemini key, with environment precedence."""

    def __init__(self, secret_dir: Path, env: dict[str, str] | None = None) -> None:
        self._secret_dir = Path(secret_dir)
        self._env = env if env is not None else os.environ

    @property
    def key_file(self) -> Path:
        return self._secret_dir / "gemini_api_key.bin"

    def env_key(self) -> str:
        return _clean_env_key(self._env.get(ENV_VAR))

    def get_api_key(self) -> tuple[str | None, str]:
        """Return ``(key, source)`` where source is environment/dpapi/none."""
        env_key = self.env_key()
        if env_key and env_key.lower() not in _PLACEHOLDERS:
            return env_key, "environment"
        if not self.key_file.exists():
            return None, "none"
        try:
            decrypted = unprotect_secret(self.key_file.read_bytes())
            key = decrypted.decode("utf-8").strip()
        except (OSError, UnicodeDecodeError, SecretStorageError) as exc:
            log.warning("Stored Gemini key could not be read: %s", exc)
            return None, "none"
        if not key:
            return None, "none"
        return key, "dpapi"

    def status(self) -> SecretStatus:
        key, source = self.get_api_key()
        if key is None:
            return SecretStatus(False, "none", "Windows DPAPI", None)
        storage = "Environment variable" if source == "environment" else "Windows DPAPI"
        return SecretStatus(True, source, storage, fingerprint(key))

    def set_api_key(self, value: str) -> SecretStatus:
        """Encrypt and persist a key. Never call this with an env-managed key."""
        cleaned = validate_api_key(value)
        self._secret_dir.mkdir(parents=True, exist_ok=True)
        encrypted = protect_secret(cleaned.encode("utf-8"))
        temporary = self.key_file.with_suffix(".bin.tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, self.key_file)
        finally:
            temporary.unlink(missing_ok=True)
        log.info("Gemini API key stored with Windows DPAPI.")
        return self.status()

    def delete_api_key(self) -> bool:
        had_file = self.key_file.exists()
        self.key_file.unlink(missing_ok=True)
        if had_file:
            log.info("Stored Gemini API key deleted.")
        return had_file

    def delete_file_only(self) -> bool:
        """Remove the DPAPI file without touching an environment-managed key."""
        return self.delete_api_key()
