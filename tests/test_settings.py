from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config.settings import AppSettings, SettingsManager


def test_defaults_load_and_validate(settings_manager: SettingsManager) -> None:
    settings = settings_manager.load()
    assert isinstance(settings, AppSettings)
    assert settings.schema_version == 1
    assert settings.gemini.model
    assert settings.agents.permission_level == 1
    assert settings.security.telemetry is False
    assert settings_manager.last_issue is None


def test_user_overrides_are_deep_merged(settings_manager: SettingsManager) -> None:
    settings_manager.paths.settings_file.write_text(
        json.dumps({"ui": {"clock_24h": False}, "monitor": {"history_points": 30}}),
        encoding="utf-8",
    )

    settings = settings_manager.load(force=True)

    assert settings.ui.clock_24h is False
    assert settings.monitor.history_points == 30
    # Unspecified keys keep their defaults.
    assert settings.ui.start_page == "dashboard"
    assert settings.monitor.refresh_seconds == 2.0


def test_invalid_settings_file_is_preserved_and_defaults_load(
    settings_manager: SettingsManager,
) -> None:
    settings_file = settings_manager.paths.settings_file
    settings_file.write_text("{not valid json", encoding="utf-8")

    settings = settings_manager.load()

    assert settings.ui.start_page == "dashboard"
    assert settings_manager.last_issue is not None
    assert not settings_file.exists()
    preserved = list(settings_file.parent.glob("settings.invalid-*.json"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_is_atomic_and_persisted(settings_manager: SettingsManager) -> None:
    settings = settings_manager.load()
    settings.ui.clock_24h = False
    saved = settings_manager.save(settings)

    assert saved.ui.clock_24h is False
    payload = json.loads(settings_manager.paths.settings_file.read_text(encoding="utf-8"))
    assert payload["ui"]["clock_24h"] is False
    assert not settings_manager.paths.settings_file.with_suffix(".json.tmp").exists()


def test_update_patches_one_section(settings_manager: SettingsManager) -> None:
    updated = settings_manager.update(ui={"window_width": 1200}, monitor={"top_process_count": 9})

    assert updated.ui.window_width == 1200
    assert updated.monitor.top_process_count == 9
    assert updated.gemini.model == settings_manager.load().gemini.model
    assert settings_manager.load(force=True).ui.window_width == 1200


def test_update_rejects_unknown_section(settings_manager: SettingsManager) -> None:
    with pytest.raises(KeyError, match="Unknown settings section"):
        settings_manager.update(not_a_section={"value": 1})


def test_invalid_values_are_rejected(settings_manager: SettingsManager) -> None:
    with pytest.raises(ValidationError):
        settings_manager.update(ui={"window_width": 200})

    with pytest.raises(ValidationError):
        settings_manager.update(gemini={"temperature": 3.0})


def test_reset_restores_defaults(settings_manager: SettingsManager) -> None:
    settings_manager.update(ui={"clock_24h": False})
    reset = settings_manager.reset()

    assert reset.ui.clock_24h is True
    assert settings_manager.load(force=True).ui.clock_24h is True


def test_safe_snapshot_contains_no_secret_material(settings_manager: SettingsManager) -> None:
    snapshot = settings_manager.safe_snapshot()

    assert snapshot["gemini"]["model"]
    serialized = json.dumps(snapshot).lower()
    assert "api_key" not in serialized
    assert "password" not in serialized
