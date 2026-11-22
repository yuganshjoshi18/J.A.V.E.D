"""Diagnostics page: verified checks, database facts and redacted local export."""

from __future__ import annotations

import platform

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_VERSION, CURRENT_PHASE, CURRENT_PHASE_NAME
from core.application import ApplicationContext
from ui.components.cards import (
    Card,
    CardHeader,
    PageHeader,
    StatusPill,
    make_button,
)
from utils.formatting import format_bytes, wrap_path
from utils.time import format_local


class DiagnosticsPage(QWidget):
    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("Page")
        self._last_export = None

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
            "Diagnostics",
            "Verified service checks and a redacted support archive that never leaves this machine "
            "unless you move it.",
            eyebrow="J.A.V.E.D. // Self-check",
        )
        self.overall_pill = StatusPill("Checking", "muted")
        header.add_action(self.overall_pill)
        run_button = make_button("Run checks", "primary")
        run_button.clicked.connect(self.refresh_checks)
        header.add_action(run_button)
        self.export_button = make_button("Export", "ghost")
        self.export_button.setToolTip("Write a redacted diagnostics report.")
        self.export_button.clicked.connect(self._export)
        header.add_action(self.export_button)
        self.layout_.addWidget(header)

        checks_card = Card()
        checks_card.body.addWidget(
            CardHeader(
                "Service health",
                "Every row is produced by a live check; there are no placeholder statuses.",
            )
        )
        self.checks_table = QTableWidget(0, 3)
        self.checks_table.setHorizontalHeaderLabels(["Component", "Status", "Evidence"])
        self.checks_table.verticalHeader().setVisible(False)
        self.checks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.checks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.checks_table.setShowGrid(False)
        self.checks_table.setMinimumHeight(300)
        head = self.checks_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        checks_card.body.addWidget(self.checks_table)
        self.checked_at = QLabel("Not run yet.")
        self.checked_at.setObjectName("Footnote")
        checks_card.body.addWidget(self.checked_at)
        self.layout_.addWidget(checks_card)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(16)

        db_card = Card()
        db_card.body.addWidget(
            CardHeader("Database", "SQLite facts, read directly from the live connection.")
        )
        self.db_labels: dict[str, QLabel] = {}
        for key, label in (
            ("path", "File"),
            ("size", "Size"),
            ("schema", "Schema"),
            ("journal", "Journal mode"),
            ("counts", "Rows"),
            ("tables", "Table counts"),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            name = QLabel(label)
            name.setObjectName("KeyLabel")
            name.setFixedWidth(108)
            value = QLabel("—")
            value.setObjectName("MonoValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(name, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(value, 1)
            holder = QWidget()
            holder.setLayout(row)
            db_card.body.addWidget(holder)
            self.db_labels[key] = value
        db_card.body.addStretch(1)
        bottom.addWidget(db_card, 3)

        env_card = Card()
        env_card.body.addWidget(
            CardHeader("Runtime", "Versions and data locations relevant to support.")
        )
        self.runtime_labels: dict[str, QLabel] = {}
        for key, label, value in (
            ("version", "Application", f"{APP_VERSION} · Phase {CURRENT_PHASE}"),
            ("phase", "Phase", CURRENT_PHASE_NAME),
            ("python", "Python", platform.python_version()),
            ("platform", "Platform", platform.platform()),
            ("data", "Data root", wrap_path(str(context.paths.data_root))),
            ("log", "Log file", wrap_path(str(context.paths.log_file))),
            ("exports", "Exports", wrap_path(str(context.paths.exports_dir))),
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            name = QLabel(label)
            name.setObjectName("KeyLabel")
            name.setFixedWidth(108)
            value_label = QLabel(value)
            value_label.setObjectName("MonoValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(name, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(value_label, 1)
            holder = QWidget()
            holder.setLayout(row)
            env_card.body.addWidget(holder)
            self.runtime_labels[key] = value_label
        env_card.body.addStretch(1)
        bottom.addWidget(env_card, 2)
        self.layout_.addLayout(bottom)

        actions_card = Card()
        actions_card.body.addWidget(
            CardHeader(
                "Support archive",
                "Includes report.json, redacted settings, environment summary and a log tail. "
                "The database, user documents and secrets are excluded.",
            )
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        export = make_button("Export ZIP", "primary")
        export.setToolTip("Write the redacted support archive as a ZIP file.")
        export.clicked.connect(self._export)
        logs = make_button("Open logs", "ghost")
        logs.setToolTip("Open the folder that holds application logs.")
        logs.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.context.paths.logs_dir)))
        )
        exports = make_button("Open exports", "ghost")
        exports.setToolTip("Open the folder that holds exported reports.")
        exports.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.context.paths.exports_dir))
            )
        )
        row.addWidget(export)
        row.addWidget(logs)
        row.addWidget(exports)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        actions_card.body.addWidget(holder)
        self.export_status = QLabel("No report exported in this session.")
        self.export_status.setObjectName("Footnote")
        self.export_status.setWordWrap(True)
        self.export_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions_card.body.addWidget(self.export_status)
        self.layout_.addWidget(actions_card)
        self.layout_.addStretch(1)

        self.refresh_checks()

    # ------------------------------------------------------------------ checks
    def set_health(self, health: dict) -> None:
        checks = health.get("checks", [])
        self.checks_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            values = [
                check.get("label", check.get("component", "")),
                check.get("status", "").replace("_", " "),
                check.get("detail", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 2:
                    item.setToolTip(str(value))
                self.checks_table.setItem(row, column, item)
        overall = health.get("overall", "muted")
        tone = {
            "ok": "ok",
            "warning": "warning",
            "error": "error",
            "not_configured": "warning",
            "unavailable": "muted",
        }.get(overall, "muted")
        self.overall_pill.set_status(tone, str(overall).replace("_", " "))
        self.checked_at.setText(
            f"Checked {format_local(health.get('checked_at'), seconds=True)} · "
            f"core operational: {'yes' if health.get('core_operational') else 'no'}"
        )

    def refresh_checks(self) -> None:
        try:
            health = self.context.refresh_health()
        except Exception as exc:
            QMessageBox.critical(self, "Health check failed", str(exc))
            return
        self.set_health(health)
        self._refresh_database()

    def _refresh_database(self) -> None:
        try:
            stats = self.context.db.stats()
        except Exception as exc:
            self.db_labels["counts"].setText(f"unavailable: {exc}")
            return
        self.db_labels["path"].setText(wrap_path(str(stats.get("path", "—"))))
        self.db_labels["size"].setText(format_bytes(stats.get("file_size_bytes")))
        self.db_labels["schema"].setText(str(stats.get("schema_version", "—")))
        self.db_labels["journal"].setText(str(stats.get("journal_mode", "—")))
        counts = stats.get("table_counts", {})
        self.db_labels["counts"].setText(str(sum(counts.values())))
        self.db_labels["tables"].setText(
            " · ".join(f"{name} {count}" for name, count in counts.items())
        )

    # ------------------------------------------------------------------ export
    def _export(self) -> None:
        self.export_button.setEnabled(False)
        try:
            target = self.context.export_diagnostics()
            self._last_export = target
            self.export_status.setText(f"Last report: {target}")
            self.export_status.setStyleSheet("color: #34d399;")
            self.refresh_checks()
            QMessageBox.information(
                self,
                "Diagnostics exported",
                f"Redacted report written to:\n\n{target}\n\n"
                "It contains no API keys, database rows or user documents.",
            )
        except Exception as exc:
            self.export_status.setText(f"Export failed: {exc}")
            self.export_status.setStyleSheet("color: #f87171;")
            QMessageBox.critical(self, "Export failed", str(exc))
        finally:
            self.export_button.setEnabled(True)
