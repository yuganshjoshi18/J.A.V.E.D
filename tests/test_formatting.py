from __future__ import annotations

import pytest

from utils.formatting import wrap_path


def test_wrap_path_preserves_text_when_zero_width_spaces_are_removed() -> None:
    original = r"C:\Users\lucky\OneDrive\Desktop\J.A.V.E.D"
    wrapped = wrap_path(original)
    assert wrapped.replace("\u200b", "") == original
    assert "\\\u200b" in wrapped


def test_wrap_path_splits_a_long_unbroken_segment() -> None:
    segment = "x" * 40
    wrapped = wrap_path("C:\\" + segment)
    assert wrapped.replace("\u200b", "") == "C:\\" + segment
    # One break after the separator plus a break every 16 characters.
    assert wrapped.count("\u200b") == 3


def test_wrap_path_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValueError):
        wrap_path("C:\\temp", chunk=0)
