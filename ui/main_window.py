"""Main window: sidebar shell, navigation and live event wiring."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_VERSION, CURRENT_PHASE, CURRENT_PHASE_NAME
from core.application import ApplicationContext
from core.event_manager import Event
from ui.agent_center import AgentCenterPage
from ui.chat_widget import ChatWidget
from ui.components.cards import StatusPill, make_button
from ui.components.nav import NavRow
from ui.dashboard import DashboardPage
from ui.diagnostics_window import DiagnosticsPage
from ui.event_bridge import EventBridge
from ui.files_window import FilesWindowPage
from ui.memory_window import MemoryWindowPage
from ui.platform import apply_dark_title_bar
from ui.research_window import ResearchWindowPage
from ui.settings_window import SettingsPage
from ui.skills_window import SkillsWindowPage
from ui.system_monitor import SystemMonitorPage
from ui.task_monitor import TaskMonitorPage
from utils.formatting import format_clock

_NAV = [
    (
        "OPERATIONS",
        [
            ("dashboard", "Dashboard", "P1"),
            ("chat", "Conversation", "LIVE"),
            ("agents", "Agent Center", "P7"),
            ("tasks", "Task Monitor", "LIVE"),
        ],
    ),
    (
        "KNOWLEDGE",
        [
            ("memory", "Memory", "P5"),
            ("research", "Research", "P9"),
            ("files", "Files & Docs", "P6"),
            ("skills", "Skills", "P13"),
        ],
    ),
    (
        "SYSTEM",
        [
            ("system", "System Monitor", "P1"),
            ("diagnostics", "Diagnostics", "P1"),
            ("settings", "Settings", "P1"),
        ],
    ),
]


class MainWindow(QMainWindow):
    def __init__(
        self,
        context: ApplicationContext,
        bridge: EventBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.bridge = bridge
        self._closing = False
        self._nav_rows: dict[str, NavRow] = {}
        self._pages: dict[str, QWidget] = {}

        self.setWindowTitle("J.A.V.E.D. — Personal Intelligence System")
        icon_path = context.paths.root / "assets" / "images" / "javed_mark.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(1120, 720)
        self._apply_initial_geometry()

        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        main_column = QWidget()
        main_column.setObjectName("MainColumn")
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_topbar())

        issue = context.settings_manager.last_issue
        if issue:
            main_layout.addWidget(self._build_issue_banner(issue))

        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        main_layout.addWidget(self.stack, 1)
        root.addWidget(main_column, 1)

        self._build_pages()

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start()
        self._update_clock()

        bridge.event_received.connect(self._on_event)
        self._load_initial_state()
        start_page = context.settings.ui.start_page
        self.go_to(start_page if start_page in self._pages else "dashboard")

    # ------------------------------------------------------------- construction
    def _apply_initial_geometry(self) -> None:
        settings = self.context.settings.ui
        screen = QApplication.primaryScreen()
        width, height = settings.window_width, settings.window_height
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - 80)
            height = min(height, available.height() - 80)
            self.resize(max(1060, width), max(700, height))
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        else:
            self.resize(width, height)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(4, 0, 0, 14)
        brand.setSpacing(10)
        mark_path = self.context.paths.root / "assets" / "images" / "javed_mark.svg"
        mark = QLabel()
        mark.setObjectName("BrandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if mark_path.exists():
            pixmap = QPixmap(str(mark_path))
            if not pixmap.isNull():
                mark.setPixmap(
                    pixmap.scaled(
                        QSize(38, 38),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        if mark.pixmap() is None or mark.pixmap().isNull():
            mark.setText("J")
        brand.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(0)
        name = QLabel("J.A.V.E.D.")
        name.setObjectName("BrandName")
        subtitle = QLabel("PERSONAL INTELLIGENCE")
        subtitle.setObjectName("BrandSub")
        brand_text.addWidget(name)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        layout.addLayout(brand)

        for section, items in _NAV:
            section_label = QLabel(section)
            section_label.setObjectName("SidebarSection")
            layout.addWidget(section_label)
            for key, label, badge in items:
                row = NavRow(key, label, badge=badge)
                row.clicked.connect(self.go_to)
                self._nav_rows[key] = row
                layout.addWidget(row)
            layout.addSpacing(8)

        layout.addStretch(1)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(8)

        phase_label = QLabel(
            f"PHASE {CURRENT_PHASE:02d} / 14 · {CURRENT_PHASE_NAME.upper()}"
        )
        phase_label.setObjectName("SidebarFooter")
        layout.addWidget(phase_label)
        version_label = QLabel(f"v{APP_VERSION} · LOCAL-FIRST · DPAPI")
        version_label.setObjectName("SidebarFooterMuted")
        layout.addWidget(version_label)
        layout.addSpacing(8)

        stop = QPushButton("EMERGENCY STOP")
        stop.setObjectName("StopButton")
        stop.setEnabled(False)
        stop.setToolTip(
            "Enabled when agent execution and audio playback ship (Phases 3–7). "
            "No agent is active in this foundation build."
        )
        layout.addWidget(stop)
        stop_hint = QLabel("NO ACTIVE AGENT · PHASE 7")
        stop_hint.setObjectName("SidebarFooterMuted")
        stop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(stop_hint)
        return sidebar

    def _build_topbar(self) -> QWidget:
        topbar = QWidget()
        topbar.setObjectName("TopBar")
        topbar.setFixedHeight(60)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)
        title = QLabel("COMMAND CONSOLE")
        title.setObjectName("TopBarTitle")
        layout.addWidget(title)
        layout.addStretch(1)
        self.top_status = StatusPill("Starting", "warning")
        layout.addWidget(self.top_status)
        divider = QFrame()
        divider.setObjectName("VerticalDivider")
        divider.setFixedSize(1, 24)
        layout.addWidget(divider)
        clock_column = QVBoxLayout()
        clock_column.setContentsMargins(0, 0, 0, 0)
        clock_column.setSpacing(0)
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setObjectName("Clock")
        self.date_label = QLabel("—")
        self.date_label.setObjectName("ClockDate")
        clock_column.addWidget(self.clock_label, 0, Qt.AlignmentFlag.AlignRight)
        clock_column.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(clock_column)
        return topbar

    def _build_issue_banner(self, issue: str) -> QWidget:
        banner = QFrame()
        banner.setObjectName("WarningBanner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(12)
        label = QLabel(f"CONFIGURATION ISSUE · {issue}")
        label.setObjectName("BannerText")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = make_button("Open diagnostics", "ghost")
        button.clicked.connect(lambda: self.go_to("diagnostics"))
        layout.addWidget(button)
        return banner

    def _build_pages(self) -> None:
        self.dashboard_page = DashboardPage(self.context)
        self.dashboard_page.navigate_requested.connect(self.go_to)
        self.chat_page = ChatWidget(self.context)
        self.agent_page = AgentCenterPage()
        self.task_page = TaskMonitorPage(self.context)
        self.memory_page = MemoryWindowPage()
        self.research_page = ResearchWindowPage()
        self.files_page = FilesWindowPage()
        self.skills_page = SkillsWindowPage()
        self.system_page = SystemMonitorPage(self.context)
        self.diagnostics_page = DiagnosticsPage(self.context)
        self.settings_page = SettingsPage(self.context)

        pages = {
            "dashboard": self.dashboard_page,
            "chat": self.chat_page,
            "agents": self.agent_page,
            "tasks": self.task_page,
            "memory": self.memory_page,
            "research": self.research_page,
            "files": self.files_page,
            "skills": self.skills_page,
            "system": self.system_page,
            "diagnostics": self.diagnostics_page,
            "settings": self.settings_page,
        }
        for key, page in pages.items():
            if hasattr(page, "navigate_requested"):
                page.navigate_requested.connect(self.go_to)
            self._pages[key] = page
            self.stack.addWidget(page)

    # ------------------------------------------------------------------ state
    def _load_initial_state(self) -> None:
        snapshot = self.context.state.snapshot
        self._apply_app_state(snapshot.to_dict())
        health = self.context.health.check_all()
        self._apply_health(health)
        self.dashboard_page.refresh_activity()
        self.settings_page.load_form()
        saved = self.context.settings_manager.load()
        self.system_page.configure_history(saved)

    def _update_clock(self) -> None:
        now = datetime.now()
        clock, date = format_clock(now, use_24h=self.context.settings.ui.clock_24h)
        self.clock_label.setText(clock)
        self.date_label.setText(date.upper())
        self.dashboard_page.update_clock(now)

    def go_to(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        for nav_key, row in self._nav_rows.items():
            row.set_active(nav_key == key)
        self.stack.setCurrentWidget(page)
        if key == "dashboard":
            self.dashboard_page.refresh_activity()
            self.dashboard_page.refresh_environment()
        elif key == "chat":
            self.chat_page.refresh()
        elif key == "tasks":
            self.task_page.refresh()
        elif key == "diagnostics":
            self.diagnostics_page.refresh_checks()

    def _apply_app_state(self, state: dict) -> None:
        status = str(state.get("status", "starting"))
        tone = {
            "ready": "ok",
            "starting": "warning",
            "degraded": "error",
            "shutting_down": "muted",
            "stopped": "muted",
        }.get(status, "muted")
        self.top_status.set_status(tone, status.replace("_", " "))
        self.top_status.setToolTip(str(state.get("detail", "")))
        self.dashboard_page.set_app_state(state)

    def _apply_health(self, health: dict) -> None:
        self.dashboard_page.set_health(health)
        self.diagnostics_page.set_health(health)
        self.chat_page.refresh_provider_status()

    # ------------------------------------------------------------------ events
    def _on_event(self, event: Event) -> None:
        if event.type == "system.metrics":
            metrics = event.get("metrics") or {}
            self.dashboard_page.update_metrics(metrics)
            self.system_page.update_metrics(metrics)
        elif event.type == "health.checked":
            health = event.get("health") or {}
            if health:
                self._apply_health(health)
        elif event.type == "state.changed":
            state = event.get("state") or {}
            if state:
                self._apply_app_state(state)
        elif event.type == "audit.recorded":
            self.dashboard_page.refresh_activity()
        elif event.type.startswith("chat."):
            self.chat_page.handle_event(event)
        elif event.type in {"task.created", "task.started", "task.finished"}:
            if self.stack.currentWidget() is self.task_page:
                self.task_page.refresh()
        elif event.type == "settings.changed":
            settings = event.get("settings")
            if settings is None:
                settings = self.context.settings
            self._update_clock()
            self.dashboard_page.refresh_environment()
            self.system_page.configure_history(settings)
            self.task_page.refresh()
            self.chat_page.refresh_provider_status()

    # ------------------------------------------------------------------ window
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_dark_title_bar(self)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        self._closing = True
        self.clock_timer.stop()
        try:
            if not self.isMaximized():
                self.context.settings_manager.update(
                    ui={"window_width": self.width(), "window_height": self.height()}
                )
        except Exception:
            pass
        self.bridge.close()
        self.context.shutdown()
        event.accept()
