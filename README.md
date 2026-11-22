# J.A.V.E.D.

**J.A.V.E.D. — Personal Intelligence System** is a local-first, safety-first AI operating
system for Windows. It is built in phases: every screen reflects what actually exists, and
capabilities that are not implemented are labelled with the phase that will deliver them.

> **Current status: Phase 1 — Foundation and UI is complete.**
> The desktop shell, configuration, secure secret storage, SQLite persistence, audit log,
> task runtime, live system telemetry, diagnostics and settings are real and tested.
> No Gemini request, voice pipeline, file tool, memory capture or agent loop runs in this
> build. Those modules are **not** simulated.

---

## What works in this build

| Area | Status | Evidence |
| --- | --- | --- |
| Qt desktop shell and navigation | Working | Every page constructs and renders offscreen in the UI test |
| Dashboard | Working | Live CPU / memory / disk / network telemetry, real health checks |
| System Monitor | Working | Real `psutil` samples, process table, volumes, JSON export |
| Task Monitor | Working | Real asyncio task registry with lifecycle and cancellation |
| Settings | Working | Pydantic validation, atomic save, DPAPI key management |
| Diagnostics | Working | Live service checks, database facts, redacted ZIP export |
| Audit log | Working | Persisted to SQLite; startup, settings and secret events recorded |
| System health | Working | Honest readiness: unavailable features are reported as unavailable |
| Conversation | **Phase 2** | Static phase-locked page; no fake replies |
| Voice input / output | **Phase 3** | Static phase-locked page; no microphone access |
| Memory Manager | **Phase 5** | Schema exists; capture and retrieval do not |
| Files & Documents | **Phase 6** | Workspace rules exist; file tools do not |
| Agent Control Center | **Phase 7** | Orchestrator, approvals and emergency stop do not |
| Research Center | **Phase 9** | No web search, no document analysis |
| Local language model | **Phase 11** | No Ollama routing |
| Skills & Integrations | **Phase 13** | No plugin or device bridge |

The **Emergency STOP** control is visible but disabled. Its tooltip states that cancellation
arrives with the agent engine in Phase 7. It is not a decorative working control.

---

## Requirements

- Windows 10 or Windows 11 (x64).
- Python **3.11–3.14, standard ABI**. Do **not** use the free-threaded `3.14t` build: the
  PySide6 wheels target the standard ABI.
- No administrator rights are required.
- An internet connection is needed only to install packages. This build makes no provider
  calls.

Verified on this workstation:

```text
Python      3.14.3
PySide6     6.11.2
psutil      7.2.1
pydantic    2.12.5
google-genai 2.23.0
pytest      9.1.1
Windows     11 (10.0.26220)
```

The Gemini SDK is installed for Phase 2 configuration checks. It is **not** invoked yet.

---

## Setup

### Recommended: one command

From the project folder in Command Prompt:

```bat
scripts\setup_windows.bat
```

The script finds a standard Python 3.11–3.14 interpreter, creates `.venv`, installs
`requirements.txt`, and runs the environment check.

### Manual setup (PowerShell or Command Prompt)

Use the same interpreter for every command. The examples use the Windows Python launcher:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\check_environment.py
```

If `py -3.14` is unavailable, replace it with `py -3.13`, `py -3.12`, or `py -3.11`.
Avoid a bare `py` if it selects a free-threaded build.

---

## Run

```bat
scripts\run_javed.bat
```

or directly:

```powershell
.venv\Scripts\python.exe main.py
```

The first launch creates the private runtime tree under
`%LOCALAPPDATA%\JAVED`. It does not write into the repository or into OneDrive.

### First-run checklist

1. Open **Diagnostics** and run the checks. Database and storage should be `ok`.
2. Open **Settings** and, if you want Phase 2 ready, paste a Gemini API key. It is encrypted
   with Windows DPAPI and never written to settings, SQLite or logs. A key alone does not
   activate intelligence; the client arrives in Phase 2.
3. Open **System Monitor** and confirm live CPU, memory, disk, network and process rows.
4. Open **Task Monitor** and confirm `system_monitor` is running.

---

## Verify

```powershell
# Full automated test suite (63 tests)
.venv\Scripts\python.exe -m pytest -q

# Syntax / import compilation
.venv\Scripts\python.exe -m compileall -q . -x "\.venv"

# Environment, dependency, configuration and SQLite migration check
.venv\Scripts\python.exe scripts\check_environment.py
```

The UI test runs Qt in **offscreen** mode. It constructs every page, checks for horizontal
overflow at the supported minimum window size, waits for live telemetry, and saves a
screenshot into pytest's temporary folder. It does not call any paid API.

Manual startup smoke test:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:JAVED_DATA_DIR = "$env:TEMP\javed-smoke"
.venv\Scripts\python.exe main.py
```

The window stays open; press `Ctrl+C` or close it. The log at
`%JAVED_DATA_DIR%\logs\javed.log` should contain `started — Phase 1` and
`System monitor started`.

---

## Configuration

Defaults live in [`config/defaults.json`](config/defaults.json) and are always read from
disk. User overrides are stored atomically at `%LOCALAPPDATA%\JAVED\config\settings.json`.
A corrupt user file is preserved as `settings.invalid-<timestamp>.json`; the app continues
with defaults and shows a banner.

Model names, token limits, timeouts, retries, voice preferences, permission levels,
workspace allowlists and monitor intervals are configuration values, not hardcoded
constants. Change the Gemini model in **Settings** when Google deprecates one — no code edit
is required.

Environment variables (see [`.env.example`](.env.example)):

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Key override; takes precedence over the DPAPI store |
| `JAVED_DATA_DIR` | Relocates the private runtime root |
| `JAVED_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

### Runtime data layout

```text
%LOCALAPPDATA%\JAVED\
├── config\settings.json
├── database\javed.db
├── reports\
├── documents\
├── exports\
├── logs\javed.log
└── secrets\gemini_api_key.bin   (DPAPI-encrypted)
```

Runtime data is deliberately outside the repository so it cannot be uploaded to GitHub or
synced by OneDrive by accident.

---

## Security and privacy model

- **API keys:** Windows DPAPI (`CryptProtectData`) with user- and machine-bound protection.
  `GEMINI_API_KEY` overrides the stored key. The UI shows only a storage label and a short
  fingerprint.
- **No key leakage:** the key is never written to settings JSON, SQLite, logs, diagnostics or
  the repository.
- **Redaction:** diagnostics reports and settings snapshots pass through the redaction
  helpers before export.
- **Workspaces:** validators reject paths outside authorised roots and fail closed when the
  list is empty. Enforcement in file tools ships in Phase 6.
- **Permissions:** levels 1–4 are persisted and explained in Settings. The agent engine that
  enforces them arrives in Phase 7.
- **Audit:** startup, shutdown, settings changes, secret changes, diagnostics exports and
  file-tool workspace changes are recorded in SQLite.
- **Network:** this build makes no outbound application calls. `allow_network` gates future
  features; telemetry is explicitly disabled and not implemented.
- **Logs:** a redacting formatter is installed before Qt starts.

### Never upload these to GitHub

```text
.env                         API keys
*.db, *.sqlite, *.db-wal     databases and journals
logs/, *.log                 application logs
*.zip                        diagnostics archives
storage/database/*           runtime data if copied into the repo
storage/documents/*
storage/exports/*
storage/reports/*
.venv/, venv/                local environments
__pycache__/, .pytest_cache/
models/, *.gguf, *.onnx      local model binaries
%LOCALAPPDATA%\JAVED\        the entire private runtime tree
```

The included [`.gitignore`](.gitignore) already blocks these patterns.

---

## Architecture

```text
main.py                     Thin bootstrap only
config/                     Pydantic settings, defaults, phase constants
core/                       Composition root, asyncio runtime, event bus, state,
                            tasks, audit, health, system monitor
memory/                     SQLite migrations and repositories
ui/                         Qt shell, pages, components, theme
utils/                      Paths, DPAPI security, redaction, diagnostics,
                            validators, logging, formatting
tests/                      Unit and offscreen UI acceptance tests
scripts/                    Windows setup, launcher, environment check
assets/                     Logo and static assets
storage/                    Placeholder layout documentation only
docs/                       Phase notes and acceptance evidence
```

Key design rules:

- The Qt GUI thread never runs the asyncio loop. Services publish events through a
  thread-safe bus; `EventBridge` converts them into queued Qt signals.
- `ApplicationContext` is the composition root. It owns the database, runtime, tasks,
  monitor, audit and health services and shuts them down in order.
- SQLite uses WAL with lock-guarded access; schema version 1 already includes future-phase
  tables while only settings, audit and task repositories are active.
- Pages are independent modules. `main.py` contains no feature logic.

See [`docs/PHASE_1.md`](docs/PHASE_1.md) for the full Phase 1 acceptance record, file list
and upload checklist.

---

## Manual upload to GitHub (website only)

No Git, Git Bash, GitHub CLI or command-line push is required.

1. Sign in to <https://github.com> and create a new **empty** repository (for example
   `JAVED`). Do not add a README or `.gitignore` during creation.
2. On the repository page, choose **Add file → Upload files**.
3. Drag these root files: `README.md`, `LICENSE`, `.gitignore`, `.env.example`,
   `requirements.txt`, `pyproject.toml`, `main.py`.
4. Drag these folders: `assets`, `config`, `core`, `docs`, `memory`, `scripts`,
   `storage`, `tests`, `ui`, `utils`. The empty `storage` subfolders contain `.gitkeep`
   files so the structure survives.
5. Use **Commit changes** with a message such as `Phase 1: foundation and UI`.
6. Wait for the file list to finish uploading. GitHub's web uploader accepts up to 100 files
   per batch; if a folder is larger, upload it in more than one pass.
7. Open the repository and verify:
   - `.env` is absent.
   - No `.venv`, `__pycache__`, `.pytest_cache`, `*.db`, `*.log` or `*.zip` appears.
   - `.gitignore` and `README.md` render.
   - `docs/PHASE_1.md` is present.
8. GitHub's website uploader does not run tests. Run them locally with the commands above.

If the web uploader refuses hidden files, upload `.gitignore` and `.env.example` separately
using **Add file → Create new file** and paste their contents.

---

## Phase status

Only phases with visible modules in this build are listed; all are **not started** except
Phase 1.

| Phase | Module | Status |
| --- | --- | --- |
| 1 | Foundation and UI | **Complete** |
| 2 | Gemini intelligence | Not started |
| 3 | Voice input / output | Not started |
| 5 | Persistent, user-controlled memory | Not started |
| 6 | Safe tools and Windows automation | Not started |
| 7 | Agent orchestration | Not started |
| 9 | Research and multimodal | Not started |
| 11 | Local language model routing | Not started |
| 13 | Extensibility and hardware preparation | Not started |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError` when running | Use the `.venv` interpreter, or run `scripts\setup_windows.bat` |
| Qt platform / plugin error | Do not set `QT_QPA_PLATFORM` for normal use; it is only for tests |
| `py` selects a free-threaded build | Use `py -3.14` (or another standard 3.11–3.14 interpreter) |
| Settings file rejected | The invalid file is preserved beside the new one; fix the JSON or reset defaults in Settings |
| Database locked | Close other J.A.V.E.D. instances; only one process should own the database |
| No API key warning | Expected until you add a key; Phase 2 is not active yet |

---

## License

MIT — see [`LICENSE`](LICENSE).
