"""Validated application configuration.

Model names and engine choices live in ``config/defaults.json`` (and the
per-user settings file), never hardcoded in the intelligence clients.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.diagnostics import redact_mapping
from utils.logger import get_logger
from utils.paths import AppPaths

log = get_logger("settings")

APP_NAME = "J.A.V.E.D."
APP_VERSION = "0.2.0"
CURRENT_PHASE = 2
CURRENT_PHASE_NAME = "Gemini intelligence"

class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class UISettings(_Model):
    start_page: Literal[
        "dashboard",
        "chat",
        "agents",
        "tasks",
        "memory",
        "research",
        "files",
        "skills",
        "system",
        "settings",
        "diagnostics",
    ] = "dashboard"
    window_width: int = Field(default=1360, ge=1060, le=3840)
    window_height: int = Field(default=860, ge=700, le=2160)
    clock_24h: bool = True


class GeminiSettings(_Model):
    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(ge=64, le=65536)
    timeout_seconds: float = Field(ge=5.0, le=300.0)
    max_retries: int = Field(ge=0, le=10)
    streaming: bool = True


class VoiceSettings(_Model):
    language: str = Field(default="en", min_length=2, max_length=16)
    input_device: str = "default"
    wake_word_enabled: bool = False
    wake_word: str = Field(default="hey javed", min_length=2, max_length=40)
    wake_word_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    tts_voice: str = "default"
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=0.8, ge=0.0, le=1.0)
    continuous_listening: bool = False


class AgentSettings(_Model):
    permission_level: Literal[1, 2, 3, 4] = 1
    max_iterations: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=25, ge=1, le=100)
    step_timeout_seconds: int = Field(default=120, ge=10, le=1800)
    require_confirmation_for_writes: bool = True


class MemorySettings(_Model):
    enabled: bool = True
    retention_days: int = Field(default=365, ge=1, le=3650)
    auto_capture: bool = False
    semantic_search: bool = False


class SecuritySettings(_Model):
    allowed_workspaces: list[str] = Field(default_factory=list, max_length=20)
    audit_retention_days: int = Field(default=90, ge=1, le=3650)
    allow_network: bool = True
    telemetry: bool = False

    @field_validator("allowed_workspaces")
    @classmethod
    def _normalise_workspaces(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            stripped = item.strip()
            if not stripped:
                continue
            resolved = str(Path(stripped).expanduser().resolve(strict=False))
            if resolved not in cleaned:
                cleaned.append(resolved)
        return cleaned


class MonitorSettings(_Model):
    refresh_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    history_points: int = Field(default=60, ge=10, le=240)
    top_process_count: int = Field(default=6, ge=3, le=20)


class AppSettings(_Model):
    schema_version: int = Field(default=1, ge=1)
    ui: UISettings
    gemini: GeminiSettings
    voice: VoiceSettings
    agents: AgentSettings
    memory: MemorySettings
    security: SecuritySettings
    monitor: MonitorSettings


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsManager:
    """Load, validate and atomically persist user settings.

    Defaults are always read from disk so future configuration changes do not
    require code edits. A corrupt user file is preserved (not deleted) and the
    application continues with defaults plus a visible warning.
    """

    def __init__(self, paths: AppPaths, defaults_file: Path | None = None) -> None:
        self._paths = paths
        self._defaults_file = defaults_file or paths.defaults_file
        self._lock = RLock()
        self._settings: AppSettings | None = None
        self._issue: str | None = None

    @property
    def paths(self) -> AppPaths:
        return self._paths

    @property
    def last_issue(self) -> str | None:
        return self._issue

    def _read_json(self, path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Configuration file missing: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Configuration file unreadable: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Configuration root must be a JSON object: {path}")
        return payload

    def load(self, *, force: bool = False) -> AppSettings:
        with self._lock:
            if self._settings is not None and not force:
                return self._settings

            defaults = self._read_json(self._defaults_file)
            self._issue = None
            raw = defaults
            if self._paths.settings_file.exists():
                try:
                    user_payload = self._read_json(self._paths.settings_file)
                    raw = _deep_merge(defaults, user_payload)
                except RuntimeError as exc:
                    self._issue = f"Settings file could not be read; defaults loaded. {exc}"
                    log.warning(self._issue)
                    self._preserve_invalid_settings_file()

            try:
                self._settings = AppSettings.model_validate(raw)
            except Exception as exc:
                self._issue = f"Settings validation failed; defaults loaded. {exc}"
                log.warning(self._issue)
                self._settings = AppSettings.model_validate(defaults)

            log.info(
                "Settings loaded (model=%s, permission level=%s)",
                self._settings.gemini.model,
                self._settings.agents.permission_level,
            )
            return self._settings

    def _preserve_invalid_settings_file(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self._paths.settings_file.with_name(f"settings.invalid-{stamp}.json")
        try:
            os.replace(self._paths.settings_file, target)
            log.info("Invalid settings file preserved at %s", target)
        except OSError:
            log.exception("Could not preserve the invalid settings file.")

    def save(self, settings: AppSettings) -> AppSettings:
        """Validate, then atomically replace the user settings file."""
        validated = AppSettings.model_validate(settings.model_dump(mode="json"))
        self._paths.config_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            validated.model_dump(mode="json"), indent=2, ensure_ascii=False
        )
        temporary = self._paths.settings_file.with_suffix(".json.tmp")
        with self._lock:
            try:
                temporary.write_text(payload + "\n", encoding="utf-8")
                os.replace(temporary, self._paths.settings_file)
            finally:
                temporary.unlink(missing_ok=True)
            self._settings = validated
            self._issue = None
        log.info("Settings saved.")
        return validated

    def reset(self) -> AppSettings:
        defaults = AppSettings.model_validate(self._read_json(self._defaults_file))
        return self.save(defaults)

    def safe_snapshot(self) -> dict:
        """Redacted settings for diagnostics and support reports."""
        settings = self.load()
        return redact_mapping(settings.model_dump(mode="json"))

    def update(self, **sections: dict) -> AppSettings:
        """Patch named sections (for example ``ui={...}``) and save."""
        current = self.load().model_dump(mode="json")
        for section, values in sections.items():
            if section not in current:
                raise KeyError(f"Unknown settings section: {section}")
            current[section] = _deep_merge(current[section], values)
        return self.save(AppSettings.model_validate(current))
