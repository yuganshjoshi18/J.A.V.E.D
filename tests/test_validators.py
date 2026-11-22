from __future__ import annotations

import sys
from pathlib import Path

import pytest

from utils.validators import (
    PathNotAllowed,
    is_within,
    require_within,
    sanitize_filename,
    truthy,
    validate_workspace,
)


def test_is_within_accepts_root_and_descendant(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    child = root / "nested" / "file.txt"
    child.parent.mkdir(parents=True)

    assert is_within(root, root) is True
    assert is_within(child, root) is True
    assert is_within(tmp_path / "other", root) is False


def test_require_within_enforces_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    allowed = root / "a" / "b.txt"
    allowed.parent.mkdir()

    assert require_within(allowed, [root]) == allowed.resolve()
    with pytest.raises(PathNotAllowed, match="outside every authorised workspace"):
        require_within(tmp_path / "elsewhere.txt", [root])


def test_require_within_fails_closed_without_workspaces(tmp_path: Path) -> None:
    with pytest.raises(PathNotAllowed, match="No workspaces are authorised"):
        require_within(tmp_path, [])


def test_validate_workspace_requires_existing_directory(tmp_path: Path) -> None:
    folder = tmp_path / "authorised"
    folder.mkdir()

    assert validate_workspace(folder) == folder.resolve()

    with pytest.raises(OSError):
        validate_workspace(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        validate_workspace(file_path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive roots")
def test_validate_workspace_rejects_drive_root() -> None:
    with pytest.raises(PathNotAllowed, match="whole drive"):
        validate_workspace(Path("C:\\"))


def test_sanitize_filename_replaces_invalid_characters() -> None:
    assert sanitize_filename('report: final?.txt') == "report_ final_.txt"
    assert sanitize_filename("   ") == "untitled"
    assert sanitize_filename("CON.txt") == "_CON.txt"


def test_truthy_handles_common_forms() -> None:
    assert truthy(True) is True
    assert truthy(" YES ") is True
    assert truthy("on") is True
    assert truthy("0") is False
    assert truthy(None) is False
    assert truthy(1) is True
