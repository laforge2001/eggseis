"""Tests for the canonical axis enum + tuple."""

from __future__ import annotations

import pytest

from eggseis.axes import AXES, Axis


def test_axes_tuple_matches_enum() -> None:
    assert AXES == tuple(a.value for a in Axis)


def test_axes_values() -> None:
    assert Axis.INLINE.value == "inline"
    assert Axis.XLINE.value == "xline"
    assert Axis.TIMESLICE.value == "timeslice"


def test_axis_string_coercion() -> None:
    assert Axis("inline") is Axis.INLINE
    assert Axis("xline") is Axis.XLINE
    assert Axis("timeslice") is Axis.TIMESLICE


def test_axis_invalid_string_raises() -> None:
    with pytest.raises(ValueError):
        Axis("zline")


def test_axis_is_str_subclass() -> None:
    """StrEnum members should compare equal to their string values."""
    assert Axis.INLINE == "inline"
    assert "inline" in AXES
