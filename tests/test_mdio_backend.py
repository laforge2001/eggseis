"""Integration tests for MDIOBackend against a real MDIO survey.

These tests require EGGSEIS_TEST_MDIO to point at an MDIO v1 dataset.
Otherwise they skip — they're not run in the default CI matrix until a
fixture survey is wired up.
"""

from __future__ import annotations

import numpy as np
import pytest

mdio = pytest.importorskip("mdio")
from eggseis.backends.mdio import MDIOBackend  # noqa: E402
from eggseis.data import SeismicBackend, SeismicVolume  # noqa: E402


def test_backend_satisfies_protocol(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    assert isinstance(backend, SeismicBackend)


def test_geometry_is_consistent(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    g = backend.geometry
    assert g.n_inlines > 0
    assert g.n_xlines > 0
    assert g.n_samples > 0
    assert g.shape == (g.n_inlines, g.n_xlines, g.n_samples)


def test_read_inline_shape(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    g = backend.geometry
    arr = backend.read_inline(g.inline_min)
    assert arr.shape == (g.n_xlines, g.n_samples)
    assert np.issubdtype(arr.dtype, np.floating)


def test_read_xline_shape(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    g = backend.geometry
    arr = backend.read_xline(g.xline_min)
    assert arr.shape == (g.n_inlines, g.n_samples)


def test_read_timeslice_shape(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    g = backend.geometry
    arr = backend.read_timeslice(0)
    assert arr.shape == (g.n_inlines, g.n_xlines)


def test_read_trace_shape(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    g = backend.geometry
    arr = backend.read_trace(g.inline_min, g.xline_min)
    assert arr.shape == (g.n_samples,)


def test_volume_wraps_backend(sample_mdio_path) -> None:
    backend = MDIOBackend(sample_mdio_path)
    vol = SeismicVolume(backend, name="fixture")
    assert vol.name == "fixture"
    g = vol.geometry
    arr = vol.read_inline(g.inline_min)
    assert arr.shape == (g.n_xlines, g.n_samples)
