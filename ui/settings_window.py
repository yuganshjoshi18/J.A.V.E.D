"""Functional settings page: validation, DPAPI key management and workspaces."""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import AppSettings
from core.application import ApplicationContext
from ui.components.cards import (
    Card,
    CardHeader,
    PageHeader,
    StatusPill,
    make_button,
)
from utils.formatting import wrap_path
from utils.security import SecretStorageError
from utils.validators import PathNotAllowed, validate_workspace


class SettingsPage(QWidget):
    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("Page")
        self._loading = False
        self._workspaces: list[str] = []
        self._dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("PageContent")
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(28, 24, 28, 24)
        self.layout_.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header = PageHeader(
            "Settings",
            "Configuration is validated with Pydantic and stored per user, outside the repository.",
            eyebrow="J.A.V.E.D. // Control Plane",
        )
        self.state_pill = StatusPill("Saved", "ok")
        header.add_action(self.state_pill)
        revert_button = make_button("Revert", "ghost")
        revert_button.clicked.connect(self._revert)
        save_button = make_button("Save settings", "primary")
        save_button.clicked.connect(self._save)
        header.add_action(revert_button)
        header.add_action(save_button)
        self.layout_.addWidget(header)

        self.layout_.addWidget(self._build_key_card())
        self.layout_.addWidget(self._build_gemini_card())
        self.layout_.addWidget(self._build_agents_card())
        self.layout_.addWidget(self._build_voice_card())
        self.layout_.addWidget(self._build_memory_card())
        self.layout_.addWidget(self._build_monitor_card())
        self.layout_.addWidget(self._build_workspaces_card())
        self.layout_.addWidget(self._build_security_card())
        self.layout_.addWidget(self._build_data_card())
        self.layout_.addStretch(1)

        self._connect_dirty_signals()
        self.load_form()

    def _connect_dirty_signals(self) -> None:
        for line_edit in (self.key_input, self.model_input, self.wake_word_input, self.language_input):
            line_edit.textChanged.connect(self._mark_dirty)
        for spin in (
            self.temperature_spin,
            self.max_tokens_spin,
            self.timeout_spin,
            self.retries_spin,
            self.max_iterations_spin,
            self.max_tool_calls_spin,
            self.step_timeout_spin,
            self.wake_sensitivity_spin,
            self.tts_rate_spin,
            self.tts_volume_spin,
            self.retention_spin,
            self.refresh_spin,
            self.history_spin,
            self.top_processes_spin,
            self.audit_retention_spin,
        ):
            spin.valueChanged.connect(self._mark_dirty)
        for check in (
            self.streaming_check,
            self.confirm_writes_check,
            self.wake_check,
            self.memory_enabled_check,
            self.allow_network_check,
        ):
            check.toggled.connect(self._mark_dirty)
        self.permission_combo.currentIndexChanged.connect(self._mark_dirty)

    # --------------------------------------------------------------- helpers
    def _field_row(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(16)
        name = QLabel(label)
        name.setObjectName("FieldLabel")
        name.setFixedWidth(190)
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(name, 0)
        line.addWidget(widget, 1)
        layout.addLayout(line)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("FieldHint")
            hint_label.setWordWrap(True)
            hint_label.setContentsMargins(206, 0, 0, 0)
            layout.addWidget(hint_label)
        return row

    @staticmethod
    def _spin(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        spin.setMaximumWidth(180)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        return spin

    @staticmethod
    def _double_spin(
        minimum: float, maximum: float, step: float, decimals: int = 1, suffix: str = ""
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        spin.setMaximumWidth(180)
        return spin

    # ------------------------------------------------------------------ cards
    def _build_key_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Gemini credentials",
                "The key is encrypted with Windows DPAPI or supplied through the environment. "
                "It is never written to settings, SQLite or logs.",
            )
        )
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        self.key_pill = StatusPill("Checking", "muted")
        self.key_detail = QLabel("Reading secure storage…")
        self.key_detail.setObjectName("BodyCopy")
        self.key_detail.setWordWrap(True)
        status_row.addWidget(self.key_pill, 0)
        status_row.addWidget(self.key_detail, 1)
        status_holder = QWidget()
        status_holder.setLayout(status_row)
        card.body.addWidget(status_holder)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Paste a new Gemini API key")
        self.key_input.setClearButtonEnabled(True)
        card.body.addWidget(
            self._field_row(
                "New API key",
                self.key_input,
                "Saving an empty field is rejected. Use Remove stored key to delete the DPAPI copy.",
            )
        )

        buttons = QHBoxLayout()
        buttons.setContentsMargins(206, 0, 0, 0)
        buttons.setSpacing(8)
        save_key = make_button("Save key", "primary")
        save_key.clicked.connect(self._save_key)
        self.remove_key_button = make_button("Remove key", "danger")
        self.remove_key_button.clicked.connect(self._remove_key)
        refresh = make_button("Refresh status", "ghost")
        refresh.clicked.connect(self._refresh_key_status)
        buttons.addWidget(save_key)
        buttons.addWidget(self.remove_key_button)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        holder = QWidget()
        holder.setLayout(buttons)
        card.body.addWidget(holder)

        note = QLabel(
            "A configured key enables the Conversation page; each request is attempted live "
            "and any provider error is shown to you. No test call is faked on this page."
        )
        note.setObjectName("Footnote")
        note.setWordWrap(True)
        card.body.addWidget(note)
        return card

    def _build_gemini_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Gemini configuration",
                "Provider and model choices are configuration, not hardcoded constants.",
            )
        )
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("e.g. gemini-2.5-flash")
        self.temperature_spin = self._double_spin(0.0, 2.0, 0.1, 2)
        self.max_tokens_spin = self._spin(64, 65536, " tokens")
        self.timeout_spin = self._double_spin(5.0, 300.0, 5.0, 0, " s")
        self.retries_spin = self._spin(0, 10)
        self.streaming_check = QCheckBox("Request streaming")

        card.body.addWidget(
            self._field_row(
                "Model",
                self.model_input,
                "Edit this when Google deprecates a model; no code change is required.",
            )
        )
        card.body.addWidget(self._field_row("Temperature", self.temperature_spin))
        card.body.addWidget(self._field_row("Max output tokens", self.max_tokens_spin))
        card.body.addWidget(self._field_row("Request timeout", self.timeout_spin))
        card.body.addWidget(self._field_row("Retry limit", self.retries_spin))
        card.body.addWidget(
            self._field_row(
                "Streaming",
                self.streaming_check,
                "Request streamed tokens as they arrive (used by the Conversation page).",
            )
        )
        return card

    def _build_agents_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Agent safety",
                "Enforcement ships with the orchestrator (Phase 7). These values are persisted now.",
            )
        )
        self.permission_combo = QComboBox()
        self.permission_combo.addItem("Level 1 — Read only", 1)
        self.permission_combo.addItem("Level 2 — Low-risk, reversible actions", 2)
        self.permission_combo.addItem("Level 3 — Confirm before consequential actions", 3)
        self.permission_combo.addItem("Level 4 — Restricted; never autonomous", 4)
        self.permission_combo.setMaximumWidth(420)
        self.permission_detail = QLabel("")
        self.permission_detail.setObjectName("FieldHint")
        self.permission_detail.setContentsMargins(206, 0, 0, 0)
        self.permission_detail.setWordWrap(True)
        self.permission_combo.currentIndexChanged.connect(self._update_permission_detail)

        self.max_iterations_spin = self._spin(1, 50)
        self.max_tool_calls_spin = self._spin(1, 100)
        self.step_timeout_spin = self._spin(10, 1800, " s")
        self.confirm_writes_check = QCheckBox("Confirm file writes")

        card.body.addWidget(
            self._field_row("Permission level", self.permission_combo)
        )
        card.body.addWidget(self.permission_detail)
        card.body.addWidget(self._field_row("Max iterations", self.max_iterations_spin))
        card.body.addWidget(self._field_row("Max tool calls", self.max_tool_calls_spin))
        card.body.addWidget(self._field_row("Step timeout", self.step_timeout_spin))
        card.body.addWidget(self._field_row("Write confirmation", self.confirm_writes_check))
        return card

    def _build_voice_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Voice",
                "Saved preferences for the Phase 3 voice pipeline. No microphone or speech "
                "engine is active in this build.",
            )
        )
        self.wake_check = QCheckBox("Enable wake word")
        self.wake_word_input = QLineEdit()
        self.wake_sensitivity_spin = self._double_spin(0.0, 1.0, 0.05, 2)
        self.language_input = QLineEdit()
        self.language_input.setMaximumWidth(180)
        self.tts_rate_spin = self._double_spin(0.5, 2.0, 0.05, 2, " ×")
        self.tts_volume_spin = self._double_spin(0.0, 1.0, 0.05, 2)

        card.body.addWidget(self._field_row("Wake word", self.wake_check))
        card.body.addWidget(self._field_row("Phrase", self.wake_word_input))
        card.body.addWidget(self._field_row("Detection sensitivity", self.wake_sensitivity_spin))
        card.body.addWidget(self._field_row("Language", self.language_input))
        card.body.addWidget(self._field_row("Speech rate", self.tts_rate_spin))
        card.body.addWidget(self._field_row("Speech volume", self.tts_volume_spin))
        return card

    def _build_memory_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Memory and privacy",
                "The memory manager and its review UI arrive in Phase 5. Nothing is captured today.",
            )
        )
        self.memory_enabled_check = QCheckBox("Allow memory features")
        self.retention_spin = self._spin(1, 3650, " days")
        self.auto_capture_check = QCheckBox("Auto-propose memories")
        self.auto_capture_check.setEnabled(False)
        self.auto_capture_check.setToolTip("Enabled with the Phase 5 memory manager.")
        self.auto_capture_check.setChecked(False)
        self.semantic_check = QCheckBox("Semantic search")
        self.semantic_check.setEnabled(False)
        self.semantic_check.setToolTip("Evaluated in Phase 11; not installed.")

        card.body.addWidget(self._field_row("Memory", self.memory_enabled_check))
        card.body.addWidget(self._field_row("Retention", self.retention_spin))
        card.body.addWidget(self._field_row("Auto-capture", self.auto_capture_check))
        card.body.addWidget(
            self._field_row(
                "Semantic search",
                self.semantic_check,
                "A local vector store is evaluated in Phase 11; nothing is installed today.",
            )
        )
        return card

    def _build_monitor_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader("Telemetry", "Controls the live system monitor and its history.")
        )
        self.refresh_spin = self._double_spin(0.5, 30.0, 0.5, 1, " s")
        self.history_spin = self._spin(10, 240, " points")
        self.top_processes_spin = self._spin(3, 20)
        card.body.addWidget(self._field_row("Refresh interval", self.refresh_spin))
        card.body.addWidget(self._field_row("Chart history", self.history_spin))
        card.body.addWidget(self._field_row("Top processes", self.top_processes_spin))
        return card

    def _build_workspaces_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader(
                "Authorised workspaces",
                "File tools will be confined to these folders from Phase 6. An empty list "
                "blocks all file operations by design.",
            )
        )
        self.workspace_list = QListWidget()
        self.workspace_list.setFixedHeight(110)
        card.body.addWidget(self.workspace_list)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        add = make_button("Add folder", "ghost")
        add.clicked.connect(self._add_workspace)
        remove = make_button("Remove selected", "ghost")
        remove.clicked.connect(self._remove_workspace)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        holder = QWidget()
        holder.setLayout(buttons)
        card.body.addWidget(holder)
        return card

    def _build_security_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader("Security and data", "Platform safety boundaries and retention.")
        )
        self.audit_retention_spin = self._spin(1, 3650, " days")
        self.allow_network_check = QCheckBox("Allow network access")
        self.telemetry_check = QCheckBox("Send anonymous telemetry")
        self.telemetry_check.setChecked(False)
        self.telemetry_check.setEnabled(False)
        self.telemetry_check.setToolTip("J.A.V.E.D. does not implement telemetry.")
        card.body.addWidget(self._field_row("Audit retention", self.audit_retention_spin))
        card.body.addWidget(self._field_row("Network access", self.allow_network_check))
        card.body.addWidget(self._field_row("Telemetry", self.telemetry_check))
        return card

    def _build_data_card(self) -> Card:
        card = Card()
        card.body.addWidget(
            CardHeader("Local data", "Everything below stays on this computer unless you export it.")
        )
        for label, value in (
            ("Data directory", str(self.context.paths.data_root)),
            ("Database", str(self.context.paths.database_file)),
            ("Logs", str(self.context.paths.logs_dir)),
            ("Exports", str(self.context.paths.exports_dir)),
        ):
            value = wrap_path(value)
            row = QLabel(f"{label}:  {value}")
            row.setObjectName("MonoValue")
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.setWordWrap(True)
            card.body.addWidget(row)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 6, 0, 0)
        open_data = make_button("Open data folder", "ghost")
        open_data.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.context.paths.data_root))
            )
        )
        reset = make_button("Reset defaults", "danger")
        reset.clicked.connect(self._reset_defaults)
        buttons.addWidget(open_data)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        holder = QWidget()
        holder.setLayout(buttons)
        card.body.addWidget(holder)
        return card

    # ------------------------------------------------------------------- data
    def load_form(self) -> None:
        settings = self.context.settings
        self._loading = True
        try:
            self.model_input.setText(settings.gemini.model)
            self.temperature_spin.setValue(settings.gemini.temperature)
            self.max_tokens_spin.setValue(settings.gemini.max_output_tokens)
            self.timeout_spin.setValue(settings.gemini.timeout_seconds)
            self.retries_spin.setValue(settings.gemini.max_retries)
            self.streaming_check.setChecked(settings.gemini.streaming)

            index = self.permission_combo.findData(settings.agents.permission_level)
            self.permission_combo.setCurrentIndex(max(0, index))
            self.max_iterations_spin.setValue(settings.agents.max_iterations)
            self.max_tool_calls_spin.setValue(settings.agents.max_tool_calls)
            self.step_timeout_spin.setValue(settings.agents.step_timeout_seconds)
            self.confirm_writes_check.setChecked(settings.agents.require_confirmation_for_writes)

            self.wake_check.setChecked(settings.voice.wake_word_enabled)
            self.wake_word_input.setText(settings.voice.wake_word)
            self.wake_sensitivity_spin.setValue(settings.voice.wake_word_sensitivity)
            self.language_input.setText(settings.voice.language)
            self.tts_rate_spin.setValue(settings.voice.tts_rate)
            self.tts_volume_spin.setValue(settings.voice.tts_volume)

            self.memory_enabled_check.setChecked(settings.memory.enabled)
            self.retention_spin.setValue(settings.memory.retention_days)

            self.refresh_spin.setValue(settings.monitor.refresh_seconds)
            self.history_spin.setValue(settings.monitor.history_points)
            self.top_processes_spin.setValue(settings.monitor.top_process_count)

            self._workspaces = list(settings.security.allowed_workspaces)
            self._render_workspaces()
            self.audit_retention_spin.setValue(settings.security.audit_retention_days)
            self.allow_network_check.setChecked(settings.security.allow_network)

            self._update_permission_detail()
            self._refresh_key_status()
            self._set_dirty(False)
        finally:
            self._loading = False

    def _collect(self) -> AppSettings:
        payload = self.context.settings.model_dump(mode="json")
        payload["gemini"] = {
            "model": self.model_input.text().strip(),
            "temperature": self.temperature_spin.value(),
            "max_output_tokens": self.max_tokens_spin.value(),
            "timeout_seconds": self.timeout_spin.value(),
            "max_retries": self.retries_spin.value(),
            "streaming": self.streaming_check.isChecked(),
        }
        payload["agents"] = {
            "permission_level": int(self.permission_combo.currentData()),
            "max_iterations": self.max_iterations_spin.value(),
            "max_tool_calls": self.max_tool_calls_spin.value(),
            "step_timeout_seconds": self.step_timeout_spin.value(),
            "require_confirmation_for_writes": self.confirm_writes_check.isChecked(),
        }
        payload["voice"].update(
            {
                "wake_word_enabled": self.wake_check.isChecked(),
                "wake_word": self.wake_word_input.text().strip(),
                "wake_word_sensitivity": self.wake_sensitivity_spin.value(),
                "language": self.language_input.text().strip(),
                "tts_rate": self.tts_rate_spin.value(),
                "tts_volume": self.tts_volume_spin.value(),
            }
        )
        payload["memory"].update(
            {
                "enabled": self.memory_enabled_check.isChecked(),
                "retention_days": self.retention_spin.value(),
                "auto_capture": False,
                "semantic_search": False,
            }
        )
        payload["monitor"] = {
            "refresh_seconds": self.refresh_spin.value(),
            "history_points": self.history_spin.value(),
            "top_process_count": self.top_processes_spin.value(),
        }
        payload["security"].update(
            {
                "allowed_workspaces": list(self._workspaces),
                "audit_retention_days": self.audit_retention_spin.value(),
                "allow_network": self.allow_network_check.isChecked(),
                "telemetry": False,
            }
        )
        return AppSettings.model_validate(payload)

    def _save(self) -> None:
        try:
            candidate = self._collect()
            self.context.save_settings(candidate)
        except ValidationError as exc:
            QMessageBox.warning(
                self,
                "Invalid settings",
                "Some values were rejected:\n\n" + "\n".join(
                    f"• {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                    for error in exc.errors()
                ),
            )
            return
        except Exception as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            return

        self.context.refresh_health()
        self.load_form()
        saved_at = datetime.now().strftime("%H:%M:%S")
        self.state_pill.set_status("ok", f"Saved {saved_at}")

    def _revert(self) -> None:
        self.load_form()
        self.state_pill.set_status("muted", "Reverted")

    def _reset_defaults(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset settings",
            "Restore every setting to config/defaults.json?\n\n"
            "The stored Gemini API key and authorised workspaces are not part of the "
            "defaults file and will be reset. The encrypted key is kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.settings_manager.reset()
            self.context.settings = self.context.settings_manager.load(force=True)
        except Exception as exc:
            QMessageBox.critical(self, "Reset failed", str(exc))
            return
        self.context.monitor.set_interval(self.context.settings.monitor.refresh_seconds)
        self.context.collector.set_top_process_count(
            self.context.settings.monitor.top_process_count
        )
        self.context.audit.record("settings", "reset_to_defaults", actor="user")
        self.context.refresh_health()
        self.load_form()
        self.state_pill.set_status("ok", "Defaults restored")
        self.context.bus.emit("settings.changed", source="settings_page")

    def _mark_dirty(self, *args) -> None:
        del args
        if self._loading:
            return
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self.state_pill.set_status("warning", "Unsaved changes")
        elif self.state_pill.property("tone") in ("warning", "error"):
            self.state_pill.set_status("ok", "Saved")

    # --------------------------------------------------------------- key mgmt
    def _refresh_key_status(self) -> None:
        status = self.context.secrets.status()
        if status.configured:
            self.key_pill.set_status("ok", "Key configured")
            self.key_detail.setText(
                f"{status.storage} · fingerprint {status.fingerprint}. "
                "The key itself is never displayed or logged."
            )
        else:
            self.key_pill.set_status("warning", "Not configured")
            self.key_detail.setText(
                "Add a Gemini API key below or set GEMINI_API_KEY. "
                "Without a key, the Conversation page will refuse to send messages."
            )
        self.remove_key_button.setEnabled(status.source == "dpapi")

    def _save_key(self) -> None:
        raw = self.key_input.text()
        try:
            self.context.secrets.set_api_key(raw)
        except (ValueError, SecretStorageError) as exc:
            QMessageBox.warning(self, "Key not saved", str(exc))
            return
        self.key_input.clear()
        self.context.audit.record(
            "secrets", "gemini_key_stored", detail={"backend": "Windows DPAPI"}, actor="user"
        )
        self._refresh_key_status()
        self.context.refresh_health()
        QMessageBox.information(
            self,
            "Key stored",
            "The Gemini API key was encrypted with Windows DPAPI.\n"
            "No plaintext copy was written.",
        )

    def _remove_key(self) -> None:
        source = self.context.secrets.status().source
        if source != "dpapi":
            return
        confirm = QMessageBox.question(
            self,
            "Remove stored key",
            "Delete the DPAPI-encrypted Gemini key from this computer?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        removed = self.context.secrets.delete_api_key()
        if removed:
            self.context.audit.record("secrets", "gemini_key_deleted", actor="user")
        self._refresh_key_status()
        self.context.refresh_health()

    # --------------------------------------------------------------- workspace
    def _render_workspaces(self) -> None:
        self.workspace_list.clear()
        if not self._workspaces:
            self.workspace_list.addItem("No workspaces authorised — file tools stay blocked.")
            self.workspace_list.setEnabled(False)
            return
        self.workspace_list.setEnabled(True)
        for path in self._workspaces:
            self.workspace_list.addItem(path)

    def _add_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Authorise a workspace folder", str(self.context.paths.documents_dir)
        )
        if not selected:
            return
        try:
            resolved = str(validate_workspace(selected))
        except (OSError, PathNotAllowed) as exc:
            QMessageBox.warning(self, "Workspace rejected", str(exc))
            return
        if resolved in self._workspaces:
            return
        if len(self._workspaces) >= 20:
            QMessageBox.warning(self, "Limit reached", "At most 20 workspaces can be authorised.")
            return
        self._workspaces.append(resolved)
        self._render_workspaces()
        self._mark_dirty()

    def _remove_workspace(self) -> None:
        if not self._workspaces:
            return
        row = self.workspace_list.currentRow()
        if row < 0 or row >= len(self._workspaces):
            return
        removed = self._workspaces.pop(row)
        self._render_workspaces()
        self.context.audit.record(
            "settings",
            "workspace_removed_pending_save",
            detail={"path": removed},
            actor="user",
        )
        self._mark_dirty()

    def _update_permission_detail(self, *args) -> None:
        del args
        descriptions = {
            1: "Read approved information and answer questions. No writes.",
            2: "Reversible actions: notes, searches, prepared reports.",
            3: "Consequential actions pause for explicit confirmation.",
            4: "High-impact actions remain blocked; the agent may only explain options.",
        }
        level = int(self.permission_combo.currentData() or 1)
        self.permission_detail.setText(
            f"{descriptions.get(level, '')} Enforcement is implemented with the agent engine in Phase 7."
        )
