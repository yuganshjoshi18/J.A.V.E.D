"""Formatting helpers shared by the UI and diagnostics."""

from __future__ import annotations

from datetime import datetime


def format_bytes(value: float | int | None, *, per_second: bool = False) -> str:
    if value is None:
        return "—"
    value = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while abs(value) >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    suffix = f"{units[index]}/s" if per_second else units[index]
    if index == 0:
        return f"{value:.0f} {suffix}"
    return f"{value:.1f} {suffix}"


def format_percent(value: float | None, *, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def wrap_path(value: str, *, chunk: int = 16) -> str:
    """Insert zero-width breaks after separators and inside long path segments.

    Windows paths can contain long unbroken folder names (for example pytest's
    temporary directories). Breaking only at separators is not enough for those,
    so a long segment is additionally split every ``chunk`` characters. The
    zero-width space never renders; it only gives wrapped labels a legal break
    opportunity.
    """
    if chunk < 1:
        raise ValueError("chunk must be at least 1")
    parts: list[str] = []
    run = 0
    for character in value:
        parts.append(character)
        if character in "\\/":
            parts.append("\u200b")
            run = 0
            continue
        run += 1
        if run % chunk == 0:
            parts.append("\u200b")
    return "".join(parts)


def format_clock(now: datetime, *, use_24h: bool = True) -> tuple[str, str]:
    clock = now.strftime("%H:%M:%S") if use_24h else now.strftime("%I:%M:%S %p")
    date = now.strftime("%A, %d %B %Y")
    return clock, date
