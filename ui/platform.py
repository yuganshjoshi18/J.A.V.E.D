"""Windows-specific native window niceties (safe no-ops elsewhere)."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QWidget

from utils.logger import get_logger

log = get_logger("platform")

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


def apply_dark_title_bar(widget: QWidget) -> None:
    """Ask DWM for a dark title bar and rounded corners on Windows 11."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(enabled),
            ctypes.sizeof(enabled),
        )
        rounded = ctypes.c_int(_DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(rounded),
            ctypes.sizeof(rounded),
        )
    except Exception:
        log.debug("Dark title bar could not be applied.", exc_info=True)


def set_app_user_model_id(app_id: str = "JAVED.PersonalIntelligence.1") -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        log.debug("AppUserModelID could not be set.", exc_info=True)
