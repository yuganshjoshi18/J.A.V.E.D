"""Shared pytest fixtures.

Qt is forced into offscreen mode before any PySide6 import so the UI tests can
run without a visible desktop session. Every fixture writes only inside the
pytest temporary directory; no test touches %LOCALAPPDATA%\\JAVED.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core.async_runtime import AsyncRuntime
from core.event_manager import EventBus
from utils.paths import PROJECT_ROOT, AppPaths


def make_paths(data_root) -> AppPaths:
    """Build an isolated AppPaths tree rooted in a temporary folder."""
    from pathlib import Path

    data = Path(data_root)
    paths = AppPaths(
        root=PROJECT_ROOT,
        data_root=data,
        config_dir=data / "config",
        database_dir=data / "database",
        logs_dir=data / "logs",
        exports_dir=data / "exports",
        reports_dir=data / "reports",
        documents_dir=data / "documents",
        secrets_dir=data / "secrets",
        assets_dir=PROJECT_ROOT / "assets",
    )
    paths.ensure()
    return paths


@pytest.fixture
def app_paths(tmp_path):
    return make_paths(tmp_path / "data")


@pytest.fixture
def settings_manager(app_paths):
    from config.settings import SettingsManager

    return SettingsManager(app_paths)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def async_runtime():
    runtime = AsyncRuntime()
    runtime.start()
    try:
        yield runtime
    finally:
        runtime.shutdown(timeout=5.0)


@pytest.fixture(scope="session")
def qapp():
    """One offscreen QApplication for the whole test session."""
    from PySide6.QtWidgets import QApplication

    from ui.theme import load_stylesheet

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyle("Fusion")
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)
    yield app
