"""Canonical axis names used across the section viewer, slice navigator,
and any code that needs to dispatch on inline / xline / timeslice."""

from __future__ import annotations

from enum import StrEnum


class Axis(StrEnum):
    INLINE = "inline"
    XLINE = "xline"
    TIMESLICE = "timeslice"


AXES: tuple[str, ...] = tuple(a.value for a in Axis)
