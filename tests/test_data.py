"""Tests for the SeismicVolume / SurveyGeometry abstractions."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from eggseis.axes import Axis
from eggseis.data import SeismicBackend, SeismicVolume, SurveyGeometry


def _geom(**overrides) -> SurveyGeometry:
    base = dict(
        inline_min=100, inline_max=199, inline_step=1,
        xline_min=300, xline_max=399, xline_step=2,
        n_samples=512, sample_rate_ms=4.0,
    )
    base.update(overrides)
    return SurveyGeometry(**base)


def test_geometry_shape_and_counts() -> None:
    g = SurveyGeometry(
        inline_min=100, inline_max=199, inline_step=1,
        xline_min=300, xline_max=399, xline_step=1,
        n_samples=512, sample_rate_ms=4.0,
    )
    assert g.n_inlines == 100
    assert g.n_xlines == 100
    assert g.shape == (100, 100, 512)
    assert g.time_max_ms == 511 * 4.0


def test_geometry_with_step() -> None:
    g = SurveyGeometry(
        inline_min=100, inline_max=200, inline_step=2,
        xline_min=300, xline_max=320, xline_step=4,
        n_samples=10, sample_rate_ms=2.0,
    )
    assert g.n_inlines == 51
    assert g.n_xlines == 6
    assert g.shape == (51, 6, 10)


def test_geometry_is_frozen() -> None:
    g = SurveyGeometry(
        inline_min=0, inline_max=9, inline_step=1,
        xline_min=0, xline_max=9, xline_step=1,
        n_samples=10, sample_rate_ms=1.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.inline_min = 999  # type: ignore[misc]


def test_fake_backend_satisfies_protocol(fake_backend) -> None:
    assert isinstance(fake_backend, SeismicBackend)


def test_volume_delegates_to_backend(fake_backend) -> None:
    vol = SeismicVolume(fake_backend, name="test")
    assert vol.name == "test"
    assert vol.shape == fake_backend.geometry.shape
    assert vol.dtype == np.dtype(np.float32)
    assert vol.geometry == fake_backend.geometry
    g = vol.geometry
    eq = np.testing.assert_array_equal
    eq(vol.read_inline(g.inline_min), fake_backend.read_inline(g.inline_min))
    eq(vol.read_xline(g.xline_min), fake_backend.read_xline(g.xline_min))
    eq(vol.read_timeslice(0), fake_backend.read_timeslice(0))
    il, xl = g.inline_min, g.xline_min
    eq(vol.read_trace(il, xl), fake_backend.read_trace(il, xl))


def test_volume_repr(fake_backend) -> None:
    vol = SeismicVolume(fake_backend, name="f3")
    text = repr(vol)
    assert "f3" in text
    assert "SeismicVolume" in text


def test_geometry_inline_at_xline_at() -> None:
    g = _geom()
    assert g.inline_at(0) == g.inline_min
    assert g.inline_at(5) == g.inline_min + 5 * g.inline_step
    assert g.xline_at(0) == g.xline_min
    assert g.xline_at(3) == g.xline_min + 3 * g.xline_step  # step=2 → 306


def test_geometry_time_at() -> None:
    g = _geom()
    assert g.time_at(0) == 0.0
    assert g.time_at(10) == 40.0
    assert g.time_at(g.n_samples - 1) == g.time_max_ms


def test_geometry_range_for_each_axis() -> None:
    g = _geom()
    assert g.range_for(Axis.INLINE) == (g.inline_min, g.inline_max, g.inline_step)
    assert g.range_for(Axis.XLINE) == (g.xline_min, g.xline_max, g.xline_step)
    assert g.range_for(Axis.TIMESLICE) == (0, g.n_samples - 1, 1)


def test_geometry_range_for_accepts_string() -> None:
    g = _geom()
    assert g.range_for("inline") == g.range_for(Axis.INLINE)
    assert g.range_for("timeslice") == g.range_for(Axis.TIMESLICE)


def test_geometry_range_for_rejects_unknown() -> None:
    g = _geom()
    with pytest.raises(ValueError):
        g.range_for("nope")


def test_volume_version_delegates_to_backend(fake_backend):
    from eggseis.data import SeismicVolume
    vol = SeismicVolume(fake_backend, name="x")
    assert vol.version == fake_backend.version
