"""Live background-task monitor.

This page lists real tasks owned by the runtime — at present the telemetry
sampler — and will automatically include agent work when Phase 7 ships.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.application import ApplicationContext
from ui.components.cards import Card, CardHeader, PageHeader, StatusPill, make_button
from utils.time import format_local


class TaskMonitorPage(QWidget):
    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("Page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("PageContent")
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(28, 24, 28, 24)
        self.layout_.setSpacing(18)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header = PageHeader(
            "Active Task Monitor",
            "Runtime tasks that are actually executing in this process.",
            eyebrow="J.A.V.E.D. // Task Telemetry",
        )
        self.active_pill = StatusPill("0 active", "muted")
        header.add_action(self.active_pill)
        prune_button = make_button("Clear finished", "ghost")
        prune_button.clicked.connect(self._prune)
        header.add_action(prune_button)
        self.layout_.addWidget(header)

        summary = Card()
        summary.body.addWidget(
            CardHeader(
                "Execution registry",
                "Owned by the background task manager. Status changes come from real task lifecycle events.",
            )
        )
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Task", "Status", "Created", "Started", "Finished", "Detail"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(320)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        summary.body.addWidget(self.table)
        self.footer = QLabel(
            "Only real background services appear here. Agent planning and execution "
            "tasks are added in Phase 7; this page will not display simulated steps."
        )
        self.footer.setObjectName("Footnote")
        self.footer.setWordWrap(True)
        summary.body.addWidget(self.footer)
        self.layout_.addWidget(summary)
        self.layout_.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        tasks = self.context.tasks.snapshot()
        active = [task for task in tasks if task["status"] in {"pending", "running"}]
        self.active_pill.set_status(
            "ok" if active else "muted",
            f"{len(active)} active",
        )
        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            detail = task.get("error") or task.get("result") or ""
            values = [
                task.get("name", ""),
                str(task.get("status", "")).replace("_", " "),
                format_local(task.get("created_at"), seconds=True),
                format_local(task.get("started_at"), seconds=True),
                format_local(task.get("finished_at"), seconds=True),
                detail,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 5:
                    item.setToolTip(str(value))
                self.table.setItem(row, column, item)
            status_item = self.table.item(row, 1)
            if status_item is not None:
                status_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )

    def _prune(self) -> None:
        removed = self.context.tasks.prune_finished(keep=20)
        self.context.audit.record(
            "tasks",
            "finished_tasks_pruned",
            detail={"removed": removed},
            actor="user",
        )
        self.refresh()
