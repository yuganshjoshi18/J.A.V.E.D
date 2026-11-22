"""Input and path validation used by tools, UI and imports.

These helpers are intentionally independent of any single feature so that the
Phase 6 tool layer can reuse the same boundary checks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class PathNotAllowed(ValueError):
    """Raised when a path escapes every authorised workspace."""


def _normalised(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve(strict=False)))


def is_within(path: str | Path, root: str | Path) -> bool:
    """True when ``path`` is ``root`` or a descendant, case-aware."""
    candidate = _normalised(Path(path))
    boundary = _normalised(Path(root))
    if candidate == boundary:
        return True
    try:
        return os.path.commonpath([candidate, boundary]) == boundary
    except ValueError:
        # Different drives on Windows.
        return False


def require_within(path: str | Path, roots: list[str | Path]) -> Path:
    """Resolve a path and require it to live inside an authorised workspace."""
    resolved = Path(path).expanduser().resolve(strict=False)
    if not roots:
        raise PathNotAllowed("No workspaces are authorised. Add one in Settings first.")
    if not any(is_within(resolved, root) for root in roots):
        raise PathNotAllowed(f"Path is outside every authorised workspace: {resolved}")
    return resolved


def validate_workspace(path: str | Path) -> Path:
    """Validate a folder the user wants to authorise for file tools."""
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a folder: {resolved}")
    if resolved == Path(resolved.anchor):
        raise PathNotAllowed("A whole drive cannot be authorised as a workspace.")
    return resolved


def sanitize_filename(name: str, fallback: str = "untitled") -> str:
    """Produce a single safe Windows filename segment."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(". ")
    if not cleaned:
        cleaned = fallback
    stem = cleaned.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:180]


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
