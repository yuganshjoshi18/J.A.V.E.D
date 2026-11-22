"""J.A.V.E.D. entry point.

Thin bootstrap only: configuration, logging, Qt application, then the
ApplicationContext and MainWindow. No business logic lives here.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from utils.logger import configure_logging, get_logger
from utils.paths import PROJECT_ROOT, resolve_paths


def _install_excepthook(logger: logging.Logger) -> None:
    def hook(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "Unexpected J.A.V.E.D. error",
                    f"{exc_type.__name__}: {exc_value}\n\n"
                    "The full traceback was written to the application log.",
                )
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    paths = resolve_paths()
    paths.ensure()
    configure_logging(paths, level=os.environ.get("JAVED_LOG_LEVEL", "INFO"))
    log = get_logger("main")
    _install_excepthook(log)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from core.application import ApplicationContext
    from ui.event_bridge import EventBridge
    from ui.main_window import MainWindow
    from ui.platform import set_app_user_model_id
    from ui.theme import load_stylesheet

    set_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("J.A.V.E.D.")
    app.setApplicationDisplayName("J.A.V.E.D. — Personal Intelligence System")
    app.setOrganizationName("J.A.V.E.D.")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)
    else:
        log.warning("Theme stylesheet could not be loaded; using default Qt styling.")

    context = None
    bridge = None
    try:
        context = ApplicationContext.create(paths)
        context.start()
        bridge = EventBridge(context.bus)
        window = MainWindow(context, bridge)
        window.show()
    except Exception as exc:
        log.exception("Startup failed.")
        QMessageBox.critical(
            None,
            "J.A.V.E.D. could not start",
            f"{type(exc).__name__}: {exc}\n\n"
            f"See the log for details:\n{paths.log_file}",
        )
        if bridge is not None:
            bridge.close()
        if context is not None:
            context.shutdown()
        return 1

    try:
        exit_code = app.exec()
    finally:
        if bridge is not None:
            bridge.close()
        if context is not None:
            context.shutdown()
    log.info("Process exiting with code %s.", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
