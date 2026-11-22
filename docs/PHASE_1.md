# Phase 1 — Foundation and UI

**Status:** complete
**Version:** 0.1.0
**Phase:** 1 of the J.A.V.E.D. roadmap
**Verified:** 2026-11-09 on Windows 11, Python 3.14.3

This document records what Phase 1 delivers, how it was verified, which files are involved,
and what must be uploaded manually to GitHub. It also states what is deliberately absent so
no later phase is mistaken for finished work.

---

## 1. Phase objective

Build a working, modular foundation for J.A.V.E.D. on Windows:

- A real Qt desktop application, not a mock-up.
- Validated configuration with no hardcoded model names.
- Secure API-key storage and honest provider readiness.
- SQLite persistence, audit logging and a background task runtime.
- Live system telemetry and a diagnostics export.
- A navigation shell where unfinished modules are clearly phase-locked.

**Phase 1 exit criteria met:**

1. The application starts, stays running and shuts down cleanly.
2. Every navigation page constructs and renders without horizontal overflow at the supported
   minimum window size.
3. Dashboard, System Monitor, Task Monitor, Settings and Diagnostics use live services.
4. Settings validate and persist; secrets use DPAPI or the environment.
5. Unfinished modules contain no simulated data, fake status or decorative controls.
6. The automated suite passes and the environment check passes.

---

## 2. Delivered functionality

### Desktop shell

- Dark navy/cyan theme in `ui/styles/theme.qss`, logo in `assets/images/javed_mark.svg`.
- Sidebar navigation grouped into Operations, Knowledge and System.
- Header clock, runtime status pill, page stack and an issue banner for invalid settings.
- Minimum window 1120×720; default 1360×860; geometry clamped to the available screen.
- Graceful shutdown closes the event bridge, cancels tasks, stops the asyncio loop and closes
  the database.

### Dashboard

- Live CPU, memory, system-drive and network tiles fed by `psutil`.
- Assistant visualiser and phase status, driven by real application state.
- Readiness column generated from live health checks.
- Recent audit activity from SQLite.
- Environment facts read from the running process and configuration.
- Responsive readiness/activity columns: side-by-side on wide windows, stacked below
  1050 px page width.

### System Monitor

- Real CPU, memory, disk, network and battery samples collected off the GUI thread.
- Sparklines for CPU, memory and network history.
- Warning heuristics for high load, low memory, low disk and battery state.
- Top-process and volume tables.
- Copy snapshot as JSON; export snapshot as JSON through a file dialog.
- Pause affects display only; sampling continues.

### Task Monitor

- Real asyncio task registry from `core/task_manager.py`.
- Create, run, complete, fail, cancel, time out and prune operations.
- Parent/child task relationships and deterministic pruning of finished tasks.
- Clear-finished action acts on persisted task state.

### Settings

- Pydantic-validated sections: UI, Gemini, voice, agents, memory, security, monitor.
- Atomic save through a temporary file and `os.replace`.
- Invalid user settings preserved and defaults loaded with a visible warning.
- Gemini key storage through Windows DPAPI, environment override, fingerprint display and
  delete confirmation.
- Workspace authorisation with fail-closed path validation and a 20-folder limit.
- Permission levels 1–4 are persisted and explained. They are not enforced yet; enforcement
  ships with the agent engine in Phase 7.
- Reset-to-defaults preserves the encrypted key.

### Diagnostics

- Live health table (database, storage, key, provider, voice, local AI, agent engine).
- Database facts read from the live SQLite connection.
- Redacted support archive export (JSON plus ZIP) containing report, redacted settings,
  environment summary and log tail; excludes the database, documents and secrets.
- Overall status pill and export path feedback.

### Core services

- `ApplicationContext` composition root and ordered startup/shutdown.
- Dedicated asyncio thread isolated from the Qt GUI thread.
- Thread-safe event bus, bridged to Qt queued signals.
- State manager with explicit statuses.
- SQLite schema v1 with WAL and lock-guarded access.
- Settings, audit and task repositories.
- Audit service writing startup, shutdown, settings, secret and diagnostics events.
- Health service that reports planned capabilities as unavailable rather than live.

### Phase-locked modules

| Page | Phase |
| --- | --- |
| Conversation | 2 — Gemini intelligence & voice |
| Voice pipeline | 3 — local speech |
| Memory Manager | 5 — persistent, user-controlled memory |
| Files & Documents | 6 — safe tools and Windows automation |
| Agent Control Center | 7 — agent orchestration |
| Research Center | 9 — research and multimodal |
| Local AI routing | 11 — local language model |
| Skills & Integrations | 13 — extensibility and hardware preparation |

Each page states that it is not available, lists planned capabilities, lists foundation facts
that already exist, and says it contains no simulated data. The test suite asserts this.

---

## 3. Architecture and threading

```text
main.py
  └── QApplication (GUI thread)
        └── MainWindow + EventBridge
               ▲ queued Qt signals
               │
        EventBus (thread-safe)
               ▲
        ApplicationContext
          ├── AsyncRuntime (dedicated loop thread)
          ├── TaskManager
          ├── SystemMonitorService → SystemMetricsCollector (psutil)
          ├── AuditService → AuditRepository
          ├── HealthService
          ├── Database (SQLite WAL)
          └── SettingsManager / SecretStore
```

- No feature logic lives in `main.py`; it only loads the environment, resolves paths,
  configures logging, builds Qt and starts the context.
- UI pages never construct their own database, loop or monitor.
- The event bridge gives Qt a queued-signal boundary, so background services never touch
  widgets directly.
- The database is accessed under an `RLock`; WAL and foreign keys are enabled.
- Schema v1 includes future-phase tables, but only settings, audit and tasks are wired now.

---

## 4. Security model

| Control | Implementation |
| --- | --- |
| API-key encryption | Windows DPAPI `CryptProtectData` with user- and machine-bound protection and fixed entropy |
| Environment override | `GEMINI_API_KEY` takes precedence; never persisted |
| Key exposure | Only backend label and short fingerprint are shown; no plaintext logging |
| Settings persistence | Pydantic validation, atomic replace, invalid file preserved |
| Workspace boundaries | `is_within`, `require_within`, `validate_workspace`; empty list fails closed |
| Permission levels | Persisted and explained; enforcement deferred to Phase 7 |
| Audit trail | Append-only SQLite events for app, settings, secrets, diagnostics and workspace changes |
| Redaction | Diagnostics and support export pass through redaction helpers; key values are masked |
| Logging | Redacting formatter installed before the Qt application starts |
| Network | No outbound provider calls in this build; telemetry disabled and not implemented |
| Runtime location | Private data under `%LOCALAPPDATA%\JAVED`, never the repository or OneDrive |

A configured key is **not** reported as a live provider. Health says the live Gemini client
arrives in Phase 2.

---

## 5. Runtime layout

```text
%LOCALAPPDATA%\JAVED\
├── config\settings.json
├── database\javed.db
├── reports\
├── documents\
├── exports\
├── logs\javed.log
└── secrets\gemini_api_key.bin
```

Overrides: `JAVED_DATA_DIR` for the root and `JAVED_LOG_LEVEL` for logging. The repository's
`storage/` folders contain only `.gitkeep` markers and documentation.

---

## 6. Verification evidence

All commands were run from the project root on 2026-11-09 with `py -3.14`.

### Automated tests

```text
py -3.14 -m pytest -q
............................................................... [100%]
63 passed
```

Distribution:

| Test file | Tests | Coverage |
| --- | ---: | --- |
| `test_database.py` | 7 | migrations, WAL, repositories, priorities, pruning |
| `test_diagnostics.py` | 4 | report redaction, ZIP export, log tail, exclusions |
| `test_event_state.py` | 6 | event bus, async delivery, state transitions |
| `test_formatting.py` | 3 | path wrapping, long segments, invalid chunk |
| `test_health.py` | 3 | honest readiness, key/provider distinction, core status |
| `test_security.py` | 12 | DPAPI round trip, environment precedence, masking, failure paths |
| `test_settings.py` | 9 | defaults, validation, atomic save, corrupt file recovery |
| `test_system_monitor.py` | 4 | real telemetry shape, clamping, interval changes |
| `test_task_manager.py` | 6 | lifecycle, timeout, cancel, parent/child, pruning |
| `test_ui_smoke.py` | 2 | every page constructs, no overflow, live telemetry, honest phase locks |
| `test_validators.py` | 7 | traversal, workspace boundaries, filenames |
| **Total** | **63** | |

No test calls a paid API. The Gemini SDK is imported only by the environment check.

### Compilation

```text
py -3.14 -m compileall -q . -x "\.venv"
```

Completed with no output (success).

### Environment check

```text
py -3.14 scripts\check_environment.py
```

All required checks `PASS`:

- Python 3.14.3 (>= 3.11, < 3.15)
- PySide6 6.11.2, psutil 7.2.1, pydantic 2.12.5
- dotenv, google-genai 2.23.0, httpx 0.28.1, pytest 9.1.1
- `config/defaults.json` parses and validates (model read from configuration)
- runtime data directory writable
- Qt application starts (offscreen)
- SQLite schema migration succeeds

### Startup smoke test

A subprocess was launched with `QT_QPA_PLATFORM=offscreen` and an isolated
`JAVED_DATA_DIR`, then terminated after six seconds. The process was still alive, and the
log contained:

```text
J.A.V.E.D. 0.1.0 started — Phase 1 (Foundation and UI).
System monitor started (interval 2.0s).
```

The non-zero exit code from the check came from the deliberate `terminate()`, not from an
application crash.

### Layout check at the supported minimum size

A script opened the application offscreen at 1120×720 and opened every page. Horizontal
scrollbar maxima were:

```text
dashboard    hmax 0
tasks        hmax 0
system       hmax 0
diagnostics  hmax 0
settings     hmax 0
```

The dashboard readiness/activity columns switched to vertical below the 1050 px page-width
threshold, as designed.

### Visual inspection note

The agent that built this phase cannot view image files. Visual quality was therefore checked
programmatically: geometry, scrollbar maxima, colours, live values and widget construction.
The UI test still writes `window.png` to pytest's temporary directory for a human to inspect.
Users should launch the app and review the visuals directly.

---

## 7. Acceptance traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Modular structure, no logic in `main.py` | `config/`, `core/`, `memory/`, `ui/`, `utils/` packages | Code review; startup path in `main.py` |
| Python 3.11+, PySide6, SQLite, Pydantic | `requirements.txt`, `pyproject.toml` | Environment check and test run |
| No hardcoded model names | `config/defaults.json` + settings model | Settings tests; model displayed from config |
| Gemini key security | DPAPI store, env override, fingerprints | `test_security.py` |
| Audit logging | `AuditService`, SQLite repository | `test_database.py`, `test_event_state.py` |
| Workspace restrictions | Validators and settings | `test_validators.py` |
| Permission levels | Persisted settings and UI explanations | `test_settings.py` |
| Redaction | Diagnostics and logger helpers | `test_diagnostics.py`, `test_security.py` |
| Real telemetry | psutil collector and monitor service | `test_system_monitor.py`, UI smoke |
| Real task lifecycle | asyncio task manager | `test_task_manager.py` |
| Honest readiness | Health service labels unavailable phases | `test_health.py` |
| No fake pages | `ComingSoonPage` stated phase, no simulated data | `test_ui_smoke.py` |
| No horizontal overflow | Responsive columns, wrapped paths, shorter action labels | `test_ui_smoke.py`, layout check |
| Clean shutdown | Context shutdown ordering | UI smoke and startup check |
| GitHub-safe repository | `.gitignore`, runtime data outside repo | Manual upload checklist below |

---

## 8. Files in Phase 1

### Root

```text
.env.example
.gitignore
LICENSE
README.md
main.py
pyproject.toml
requirements.txt
```

### Configuration and core

```text
config/__init__.py
config/defaults.json
config/settings.py
core/__init__.py
core/application.py
core/async_runtime.py
core/audit.py
core/event_manager.py
core/state_manager.py
core/task_manager.py
core/services/__init__.py
core/services/health.py
core/services/system_monitor.py
```

### Persistence

```text
memory/__init__.py
memory/database.py
memory/models.py
memory/repositories.py
```

### UI

```text
ui/__init__.py
ui/agent_center.py
ui/chat_widget.py
ui/components/__init__.py
ui/components/cards.py
ui/components/coming_soon.py
ui/components/nav.py
ui/components/sparkline.py
ui/components/visualizer.py
ui/dashboard.py
ui/diagnostics_window.py
ui/event_bridge.py
ui/files_window.py
ui/foundation.py
ui/main_window.py
ui/memory_window.py
ui/platform.py
ui/research_window.py
ui/settings_window.py
ui/skills_window.py
ui/styles/theme.qss
ui/system_monitor.py
ui/task_monitor.py
ui/theme.py
```

### Utilities

```text
utils/__init__.py
utils/diagnostics.py
utils/formatting.py
utils/logger.py
utils/paths.py
utils/security.py
utils/time.py
utils/validators.py
```

### Scripts, assets and storage placeholders

```text
scripts/check_environment.py
scripts/run_javed.bat
scripts/setup_windows.bat
assets/icons/.gitkeep
assets/images/javed_mark.svg
assets/sounds/.gitkeep
storage/README.md
storage/database/.gitkeep
storage/documents/.gitkeep
storage/exports/.gitkeep
storage/reports/.gitkeep
```

### Tests and documentation

```text
tests/conftest.py
tests/test_database.py
tests/test_diagnostics.py
tests/test_event_state.py
tests/test_formatting.py
tests/test_health.py
tests/test_security.py
tests/test_settings.py
tests/test_system_monitor.py
tests/test_task_manager.py
tests/test_ui_smoke.py
tests/test_validators.py
docs/PHASE_1.md
```

During final verification the following refinements were made and retested:

- `StatTile` minimum width reduced from 170 to 150 so five live tiles fit at the minimum
  window size.
- System Monitor and Diagnostics action labels shortened, with tooltips retained.
- Long Settings checkbox labels shortened, with explanatory hints added.
- `wrap_path()` now breaks long unbroken path segments as well as separators; this fixed
  dashboard overflow with pytest's long temporary paths.
- `tests/test_formatting.py` added to lock the path-wrapping behaviour.

---

## 9. Exact run instructions

```powershell
# Setup
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\check_environment.py

# Run
.venv\Scripts\python.exe main.py

# Verify
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q . -x "\.venv"
```

Or use `scripts\setup_windows.bat` and `scripts\run_javed.bat`.

---

## 10. Manual GitHub upload checklist

The repository is not a Git repository. Upload with the GitHub website:

- [ ] Create an empty repository (no README, no `.gitignore` generated by GitHub).
- [ ] Open **Add file → Upload files**.
- [ ] Upload root files:
  - [ ] `README.md`
  - [ ] `LICENSE`
  - [ ] `.gitignore`
  - [ ] `.env.example`
  - [ ] `requirements.txt`
  - [ ] `pyproject.toml`
  - [ ] `main.py`
- [ ] Upload folders:
  - [ ] `assets`
  - [ ] `config`
  - [ ] `core`
  - [ ] `docs`
  - [ ] `memory`
  - [ ] `scripts`
  - [ ] `storage`
  - [ ] `tests`
  - [ ] `ui`
  - [ ] `utils`
- [ ] Commit with a message such as `Phase 1: foundation and UI`.
- [ ] Confirm the uploader finished; GitHub accepts at most 100 files per batch, so repeat
      the folder upload if necessary.
- [ ] Verify the repository contains roughly 80 files and the folders above.
- [ ] Verify it does **not** contain:
  - [ ] `.env`
  - [ ] `.venv/`, `venv/`
  - [ ] `__pycache__/`, `*.pyc`
  - [ ] `.pytest_cache/`
  - [ ] `*.db`, `*.sqlite`, `*.db-wal`, `*.db-shm`
  - [ ] `logs/`, `*.log`
  - [ ] `*.zip`
  - [ ] `models/`, `*.gguf`, `*.onnx`, `*.bin`
  - [ ] Any copy of `%LOCALAPPDATA%\JAVED`
- [ ] Run the tests locally; the GitHub web uploader does not execute them.

If hidden files cannot be dragged, create `.gitignore` and `.env.example` through
**Add file → Create new file** and paste their contents.

---

## 11. Intentionally absent

These are **not** bugs and must not be presented as complete:

- Gemini requests, streaming, retries or tool calls (Phase 2).
- Microphone capture, speech-to-text, text-to-speech or wake word (Phase 3).
- Memory capture, review, retrieval or semantic search (Phase 5).
- File read/write/search tools and Windows automation (Phase 6).
- Agent planning, approvals, execution and emergency stop (Phase 7).
- Web research, citations and multimodal documents (Phase 9).
- Ollama / local model routing (Phase 11).
- Skill manifests, Android companion and ESP32-S3 bridge (Phase 13).
- Packaging/installer (`PyInstaller`) and FastAPI endpoints.
- Telemetry of any kind.
- Real network calls from the application.

The Emergency STOP button is disabled and says why in its tooltip.

---

## 12. Next phase

Phase 2 will add the verified Gemini client, streaming, retries, error classification and
conversation UI. It has **not** started. No Phase 2 code, model call or claim is included in
this delivery.
