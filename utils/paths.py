"""Filesystem layout and safe path helpers.

All mutable state lives outside the repository, under the user's local
application-data directory. This keeps credentials, databases, logs and user
documents out of GitHub uploads and out of OneDrive sync by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "JAVED"
APP_DIR_NAME = "JAVED"


def _default_data_root() -> Path:
    override = os.environ.get("JAVED_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / APP_DIR_NAME).resolve()
    # Non-Windows fallback for development and CI.
    return (Path.home() / ".local" / "share" / APP_DIR_NAME).resolve()


@dataclass(frozen=True)
class AppPaths:
    """Resolved, immutable locations used by the application."""

    root: Path
    data_root: Path
    config_dir: Path
    database_dir: Path
    logs_dir: Path
    exports_dir: Path
    reports_dir: Path
    documents_dir: Path
    secrets_dir: Path
    assets_dir: Path

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def database_file(self) -> Path:
        return self.database_dir / "javed.db"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "javed.log"

    @property
    def defaults_file(self) -> Path:
        return self.root / "config" / "defaults.json"

    def ensure(self) -> None:
        """Create every runtime directory. Safe to call repeatedly."""
        for directory in (
            self.data_root,
            self.config_dir,
            self.database_dir,
            self.logs_dir,
            self.exports_dir,
            self.reports_dir,
            self.documents_dir,
            self.secrets_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def is_writable(self) -> bool:
        """Verify the data root accepts writes without leaving a file behind."""
        probe = self.data_root / ".write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False


def resolve_paths(data_root: Path | None = None) -> AppPaths:
    """Build the application layout.

    Args:
        data_root: Optional override, primarily for tests and portable installs.
    """
    root = PROJECT_ROOT
    data = Path(data_root).expanduser().resolve() if data_root else _default_data_root()
    if data_root is None and os.environ.get("JAVED_DATA_DIR", "").strip():
        data = Path(os.environ["JAVED_DATA_DIR"]).expanduser().resolve()
    return AppPaths(
        root=root,
        data_root=data,
        config_dir=data / "config",
        database_dir=data / "database",
        logs_dir=data / "logs",
        exports_dir=data / "exports",
        reports_dir=data / "reports",
        documents_dir=data / "documents",
        secrets_dir=data / "secrets",
        assets_dir=root / "assets",
    )
