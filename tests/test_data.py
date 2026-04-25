"""Tests for the SeismicVolume / SurveyGeometry abstractions."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from eggseis.data import SeismicBackend, SeismicVolume, SurveyGeometry


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
