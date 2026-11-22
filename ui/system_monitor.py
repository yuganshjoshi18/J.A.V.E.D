"""Live system-monitor page backed by real psutil samples."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
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

from core.application import ApplicationContext
from ui.components.cards import (
    Card,
    CardHeader,
    PageHeader,
    StatTile,
    make_button,
)
from ui.components.sparkline import Sparkline
from ui.theme import ACCENT, BLUE, SUCCESS, WARNING
from utils.formatting import format_bytes, format_percent
from utils.time import format_local, humanize_seconds


def _severity(percent: float | None) -> str:
    if percent is None:
        return "normal"
    if percent >= 90:
        return "error"
    if percent >= 75:
        return "warning"
    return "normal"


class SystemMonitorPage(QWidget):
    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("Page")
        self._last_metrics: dict | None = None
        self._paused = False
        history = context.settings.monitor.history_points
        self._cpu_history: deque[float] = deque(maxlen=history)
        self._memory_history: deque[float] = deque(maxlen=history)
        self._network_history: deque[float] = deque(maxlen=history)

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
            "System Monitor",
            "Host metrics sampled every few seconds off the GUI thread.",
            eyebrow="J.A.V.E.D. // Telemetry",
        )
        self.pause_check = QCheckBox("Pause view")
        self.pause_check.setToolTip("Pauses display updates only; background sampling continues.")
        self.pause_check.toggled.connect(self._set_paused)
        copy_button = make_button("Copy", "ghost")
        copy_button.setToolTip("Copy the latest telemetry snapshot to the clipboard as JSON.")
        copy_button.clicked.connect(self._copy_snapshot)
        export_button = make_button("Export", "primary")
        export_button.setToolTip("Export the latest telemetry snapshot as a JSON file.")
        export_button.clicked.connect(self._export_snapshot)
        header.add_action(self.pause_check)
        header.add_action(copy_button)
        header.add_action(export_button)
        self.layout_.addWidget(header)

        tiles = QHBoxLayout()
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(12)
        self.cpu_tile = StatTile("CPU", "%")
        self.memory_tile = StatTile("Memory", "%")
        self.disk_tile = StatTile("System drive", "%")
        self.network_tile = StatTile("Network")
        self.battery_tile = StatTile("Battery", "%")
        for tile in (
            self.cpu_tile,
            self.memory_tile,
            self.disk_tile,
            self.network_tile,
            self.battery_tile,
        ):
            tiles.addWidget(tile)
        self.layout_.addLayout(tiles)

        self.sample_label = QLabel("Waiting for the first telemetry sample…")
        self.sample_label.setObjectName("MetaLine")
        self.layout_.addWidget(self.sample_label)

        charts = QHBoxLayout()
        charts.setContentsMargins(0, 0, 0, 0)
        charts.setSpacing(14)
        self.cpu_chart, self.cpu_sparkline, self.cpu_chart_value = self._chart_card(
            "CPU load", "Percent utilisation across all logical cores.", ACCENT
        )
        self.memory_chart, self.memory_sparkline, self.memory_chart_value = self._chart_card(
            "Memory pressure", "Physical memory utilisation.", BLUE
        )
        self.network_chart, self.network_sparkline, self.network_chart_value = self._chart_card(
            "Network throughput", "Combined receive + send rate.", SUCCESS
        )
        self.network_sparkline.set_max_value(None)
        for chart in (self.cpu_chart, self.memory_chart, self.network_chart):
            charts.addWidget(chart)
        self.layout_.addLayout(charts)

        self.warning_card = Card()
        self.warning_card.body.addWidget(
            CardHeader("Anomalies", "Heuristic thresholds applied to the latest sample.")
        )
        self.warning_summary = QLabel("Waiting for a sample.")
        self.warning_summary.setObjectName("BodyCopy")
        self.warning_summary.setWordWrap(True)
        self.warning_card.body.addWidget(self.warning_summary)
        self.layout_.addWidget(self.warning_card)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(16)

        process_card = Card()
        process_card.body.addWidget(
            CardHeader("Top processes", "Ranked by current CPU share, then memory.")
        )
        self.process_table = QTableWidget(0, 4)
        self.process_table.setHorizontalHeaderLabels(["PID", "Process", "CPU %", "Memory %"])
        self.process_table.verticalHeader().setVisible(False)
        self.process_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.process_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.process_table.setShowGrid(False)
        self.process_table.setFixedHeight(210)
        head = self.process_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        process_card.body.addWidget(self.process_table)
        bottom.addWidget(process_card, 3)

        volume_card = Card()
        volume_card.body.addWidget(
            CardHeader("Volumes", "Filesystem usage reported by Windows.")
        )
        self.volume_table = QTableWidget(0, 4)
        self.volume_table.setHorizontalHeaderLabels(["Device", "Used", "Total", "Usage"])
        self.volume_table.verticalHeader().setVisible(False)
        self.volume_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.volume_table.setShowGrid(False)
        self.volume_table.setFixedHeight(210)
        volume_head = self.volume_table.horizontalHeader()
        volume_head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            volume_head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        volume_card.body.addWidget(self.volume_table)
        bottom.addWidget(volume_card, 2)

        self.layout_.addLayout(bottom)
        self.layout_.addStretch(1)

        self.configure_history(context.settings)

    def _chart_card(self, title: str, subtitle: str, color: str) -> tuple[Card, Sparkline, QLabel]:
        card = Card()
        value_label = QLabel("—")
        value_label.setObjectName("ChartValue")
        card.body.addWidget(CardHeader(title, subtitle, action=value_label))
        sparkline = Sparkline(color=color, max_points=self.context.settings.monitor.history_points)
        sparkline.setMinimumHeight(76)
        card.body.addWidget(sparkline)
        return card, sparkline, value_label

    def configure_history(self, settings) -> None:
        """Apply a validated settings object to the live chart history."""
        points = settings.monitor.history_points
        self._cpu_history = deque(self._cpu_history, maxlen=points)
        self._memory_history = deque(self._memory_history, maxlen=points)
        self._network_history = deque(self._network_history, maxlen=points)
        self.cpu_sparkline.set_max_points(points)
        self.memory_sparkline.set_max_points(points)
        self.network_sparkline.set_max_points(points)
        self.cpu_sparkline.set_max_value(100.0)
        self.memory_sparkline.set_max_value(100.0)

    def _set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_check.setText("View paused" if paused else "Pause view")
        if not paused and self._last_metrics:
            self._apply(self._last_metrics)

    def update_metrics(self, metrics: dict) -> None:
        self._last_metrics = metrics
        if not self._paused:
            self._apply(metrics)

    def _apply(self, metrics: dict) -> None:
        cpu = metrics.get("cpu", {})
        memory = metrics.get("memory", {})
        disk = metrics.get("disk", {})
        network = metrics.get("network", {})
        battery = metrics.get("battery")
        cpu_percent = cpu.get("percent")
        memory_percent = memory.get("percent")
        disk_percent = disk.get("percent")

        self.cpu_tile.set_metric(
            format_percent(cpu_percent, digits=0),
            detail=f"{cpu.get('physical') or '?'} physical / {cpu.get('count') or '?'} logical",
            percent=cpu_percent,
            severity=_severity(cpu_percent),
        )
        self.memory_tile.set_metric(
            format_percent(memory_percent, digits=0),
            detail=(
                f"{format_bytes(memory.get('available'))} available of {format_bytes(memory.get('total'))}"
                if memory.get("total")
                else "Unavailable"
            ),
            percent=memory_percent,
            severity=_severity(memory_percent),
        )
        self.disk_tile.set_metric(
            format_percent(disk_percent, digits=0),
            detail=(
                f"{format_bytes(disk.get('free'))} free of {format_bytes(disk.get('total'))}"
                if disk.get("total")
                else "Unavailable"
            ),
            percent=disk_percent,
            severity=_severity(disk_percent),
        )
        rate_down = (network.get("rate_recv") or 0.0) + (network.get("rate_sent") or 0.0)
        self.network_tile.set_metric(
            format_bytes(rate_down, per_second=True),
            detail=f"↓ {format_bytes(network.get('rate_recv') or 0, per_second=True)} · "
            f"↑ {format_bytes(network.get('rate_sent') or 0, per_second=True)}",
            percent=None,
        )
        if battery:
            plugged = battery.get("plugged")
            self.battery_tile.set_metric(
                format_percent(battery.get("percent"), digits=0),
                detail="Charging" if plugged else "On battery",
                percent=battery.get("percent"),
                severity=(
                    "error"
                    if not plugged and (battery.get("percent") or 100) <= 15
                    else "normal"
                ),
            )
        else:
            self.battery_tile.set_metric(
                "N/A",
                detail="No battery reported by this device.",
                percent=None,
            )

        self._cpu_history.append(float(cpu_percent or 0.0))
        self._memory_history.append(float(memory_percent or 0.0))
        network_rate = (network.get("rate_recv") or 0.0) + (network.get("rate_sent") or 0.0)
        self._network_history.append(network_rate)
        self.cpu_sparkline.set_values(list(self._cpu_history))
        self.memory_sparkline.set_values(list(self._memory_history))
        self.network_sparkline.set_values(list(self._network_history))
        self.cpu_chart_value.setText(format_percent(cpu_percent, digits=0))
        self.memory_chart_value.setText(format_percent(memory_percent, digits=0))
        self.network_chart_value.setText(format_bytes(network_rate, per_second=True))

        uptime = metrics.get("uptime_seconds")
        self.sample_label.setText(
            f"Sample {format_local(metrics.get('timestamp'), seconds=True)}  ·  "
            f"Uptime {humanize_seconds(uptime) if uptime is not None else '—'}  ·  "
            f"Link {'up' if network.get('up') else 'down'}"
        )

        warnings = metrics.get("warnings") or []
        if warnings:
            self.warning_summary.setText("\n".join(f"—  {item}" for item in warnings))
            self.warning_summary.setStyleSheet(f"color: {WARNING};")
        else:
            self.warning_summary.setText("No anomalies detected in the latest sample.")
            self.warning_summary.setStyleSheet("")

        processes = metrics.get("processes") or []
        self.process_table.setRowCount(len(processes))
        for row_index, process in enumerate(processes):
            cells = [
                str(process.get("pid", "")),
                str(process.get("name", "")),
                f"{process.get('cpu_percent', 0):.1f}",
                f"{process.get('memory_percent', 0):.1f}",
            ]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.process_table.setItem(row_index, column, item)

        disks = metrics.get("disks") or []
        self.volume_table.setRowCount(len(disks))
        for row_index, volume in enumerate(disks):
            cells = [
                str(volume.get("device", "")),
                format_bytes(volume.get("used")),
                format_bytes(volume.get("total")),
                format_percent(volume.get("percent"), digits=0),
            ]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.volume_table.setItem(row_index, column, item)

    def _copy_snapshot(self) -> None:
        if not self._last_metrics:
            QMessageBox.information(self, "No sample yet", "Telemetry has not arrived yet.")
            return
        QApplication.clipboard().setText(json.dumps(self._last_metrics, indent=2))
        self.sample_label.setText(
            f"Snapshot copied to clipboard at {datetime.now().strftime('%H:%M:%S')}."
        )

    def _export_snapshot(self) -> None:
        if not self._last_metrics:
            QMessageBox.information(self, "No sample yet", "Telemetry has not arrived yet.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = self.context.paths.exports_dir / f"system-snapshot-{stamp}.json"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export system snapshot",
            str(default),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as handle:
                json.dump(self._last_metrics, handle, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", f"Could not write the snapshot:\n{exc}")
            return
        self.context.audit.record(
            "diagnostics",
            "system_snapshot_exported",
            detail={"file": filename},
            actor="user",
        )
        QMessageBox.information(self, "Snapshot exported", f"Saved to:\n{filename}")
