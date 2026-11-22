"""Environment verification for J.A.V.E.D. (Phase 2).

Run with the interpreter that will execute the app:
    python scripts/check_environment.py

Exit code 0 means all required checks passed.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_MODULES = [
    ("PySide6", "Qt desktop UI"),
    ("psutil", "system telemetry"),
    ("pydantic", "validated models"),
    ("dotenv", "environment loading"),
    ("google.genai", "Gemini SDK"),
    ("httpx", "HTTP client"),
    ("pytest", "test runner"),
]

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    print("J.A.V.E.D. environment check")
    print(f"  Interpreter : {sys.executable}")
    print(f"  Version     : {sys.version.split()[0]}")
    print(f"  Platform    : {platform.platform()}")
    print()

    version = sys.version_info
    check("Python >= 3.11", version >= (3, 11), f"{version.major}.{version.minor}.{version.micro}")
    check("Python < 3.15 (dependency window)", version < (3, 15))
    free_threaded = bool(getattr(sys, "_is_gil_enabled", lambda: True)() is False)
    if free_threaded:
        print(
            "[WARN] Free-threaded Python detected. PySide6 wheels target the standard ABI; "
            "create the venv with a standard 3.12 or 3.14 interpreter."
        )

    for module_name, purpose in REQUIRED_MODULES:
        try:
            module = importlib.import_module(module_name)
            version_text = getattr(module, "__version__", "installed")
            check(f"import {module_name}", True, f"{version_text} ({purpose})")
        except Exception as exc:
            check(f"import {module_name}", False, f"{type(exc).__name__}: {exc}")

    try:
        defaults = json.loads((ROOT / "config" / "defaults.json").read_text(encoding="utf-8"))
        check("config/defaults.json parses", isinstance(defaults, dict))
        from config.settings import AppSettings

        settings = AppSettings.model_validate(defaults)
        check("default configuration validates", True, f"model={settings.gemini.model}")
    except Exception as exc:
        check("configuration validates", False, str(exc))

    try:
        from utils.paths import resolve_paths

        paths = resolve_paths()
        paths.ensure()
        check("runtime data directory writable", paths.is_writable(), str(paths.data_root))
    except Exception as exc:
        check("runtime data directory writable", False, str(exc))

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        check("Qt application can start", True, f"Qt {qVersion()} ({os.environ['QT_QPA_PLATFORM']})")
        del app
    except Exception as exc:
        check("Qt application can start", False, f"{type(exc).__name__}: {exc}")

    try:
        from memory.database import Database
        from utils.paths import resolve_paths

        probe_path = resolve_paths().data_root / "environment-probe.db"
        db = Database(probe_path)
        db.connect()
        ok = db.ping() and db.schema_version() >= 1
        db.close()
        probe_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(probe_path) + suffix).unlink(missing_ok=True)
        check("SQLite schema migration", ok)
    except Exception as exc:
        check("SQLite schema migration", False, str(exc))

    print()
    if failures:
        print(f"RESULT: {len(failures)} required check(s) failed.")
        print("Install dependencies with: python -m pip install -r requirements.txt")
        return 1
    print("RESULT: Phase 2 environment is ready.")
    print("Voice engines are intentionally not installed; they belong to Phase 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
