"""UTC-first time helpers and human-friendly formatting."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Timezone-aware ISO-8601 timestamp, sortable as text."""
    return utc_now().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_local(value: str | datetime | None, *, seconds: bool = False) -> str:
    """Render a stored UTC timestamp in the user's local timezone."""
    if value is None:
        return "—"
    parsed = parse_iso(value) if isinstance(value, str) else value
    if parsed is None:
        return "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    fmt = "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M"
    return parsed.astimezone().strftime(fmt)


def humanize_seconds(total_seconds: float) -> str:
    total_seconds = max(0, int(total_seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def greeting_for_hour(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    if 18 <= hour < 23:
        return "Good evening"
    return "Working late"
