"""Visual tokens, stylesheet loading and small style helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

# Core palette — deep navy, cyan and electric blue.
BG = "#05070d"
BG_RAISED = "#070b14"
PANEL = "#0a101c"
PANEL_ALT = "#0d1524"
BORDER = "#16243a"
BORDER_STRONG = "#1e3352"
TEXT = "#e6f1ff"
TEXT_MUTED = "#8497b0"
TEXT_DIM = "#5c6c84"
ACCENT = "#22d3ee"
ACCENT_DIM = "#0e7490"
BLUE = "#3b82f6"
SUCCESS = "#34d399"
WARNING = "#fbbf24"
DANGER = "#f87171"

THEME_FILE = Path(__file__).resolve().parent / "styles" / "theme.qss"


def load_stylesheet() -> str:
    try:
        return THEME_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def repolish(widget: QWidget) -> None:
    """Re-evaluate dynamic QSS properties after a state change."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
