"""Tests for plugin_runner.run_on_section."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import hilbert

from eggseis.builtins.envelope import envelope
from eggseis.builtins.instantaneous_frequency import instantaneous_frequency
from eggseis.builtins.rms_amplitude import rms_amplitude
from eggseis.data import SeismicVolume
from eggseis.plugin import Param, clear_registry, trace_attribute
from eggseis.plugin_runner import compute_tile, run_on_section


@pytest.fixture
def volume(fake_backend) -> SeismicVolume:
    return SeismicVolume(fake_backend, name="test")


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    clear_registry()


def test_envelope_matches_scipy(volume):
    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), volume, "inline", volume.geometry.inline_min)
    inline = volume.read_inline(volume.geometry.inline_min)
    expected = np.abs(hilbert(inline, axis=-1)).astype(np.float32)
    assert out.shape == inline.shape
    np.testing.assert_allclose(out, expected, rtol=1e-5, atol=1e-5)


def test_xline_axis_uses_correct_reader(volume):
    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), volume, "xline", volume.geometry.xline_min)
    xline = volume.read_xline(volume.geometry.xline_min)
    assert out.shape == xline.shape  # (n_inlines, n_samples)


def test_timeslice_returns_source_unchanged(volume):
    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), volume, "timeslice", 0)
    expected = volume.read_timeslice(0)
    np.testing.assert_array_equal(out, expected)


def test_context_passed_to_plugin_when_declared(volume):
    spec = instantaneous_frequency._eggseis_spec
    out = run_on_section(spec, spec.param_model(), volume, "inline", volume.geometry.inline_min)
    inline = volume.read_inline(volume.geometry.inline_min)
    assert out.shape == inline.shape
    assert out.dtype == np.float32
    # frequencies should be finite
    assert np.isfinite(out).all()


def test_param_values_propagate(volume):
    spec = rms_amplitude._eggseis_spec
    params = spec.param_model(window=5)
    out = run_on_section(spec, params, volume, "inline", volume.geometry.inline_min)
    assert out.shape == volume.read_inline(volume.geometry.inline_min).shape
    # rms is non-negative
    assert (out >= 0).all()


def test_vectorized_plugin_called_once(volume):
    """vectorized=True receives the full 2D section in one call."""
    call_count = {"n": 0}

    @trace_attribute(name="VectGain", vectorized=True)
    def vect_gain(traces: np.ndarray, k: float = Param(2.0)):
        call_count["n"] += 1
        return traces * k

    spec = vect_gain._eggseis_spec
    out = run_on_section(spec, spec.param_model(), volume, "inline", volume.geometry.inline_min)
    inline = volume.read_inline(volume.geometry.inline_min)
    assert call_count["n"] == 1
    np.testing.assert_allclose(out, inline * 2.0)


def test_non_vectorized_plugin_called_per_trace(volume):
    call_count = {"n": 0}

    @trace_attribute(name="ScalarGain")
    def scalar_gain(trace: np.ndarray, k: float = Param(3.0)):
        call_count["n"] += 1
        return trace * k

    spec = scalar_gain._eggseis_spec
    inline = volume.read_inline(volume.geometry.inline_min)
    run_on_section(spec, spec.param_model(), volume, "inline", volume.geometry.inline_min)
    assert call_count["n"] == inline.shape[0]


def test_compute_tile_writes_only_requested_range(fake_backend):
    vol = SeismicVolume(fake_backend)
    section = vol.read_inline(vol.geometry.inline_min)
    out = np.zeros_like(section, dtype=np.float32)

    spec = envelope._eggseis_spec
    context = {"sample_rate_ms": vol.geometry.sample_rate_ms,
               "axis": "inline", "index": vol.geometry.inline_min}
    compute_tile(spec, {}, context, start=2, stop=5, out=out, section=section)

    # Rows 2..4 written, others untouched.
    assert (out[:2] == 0).all()
    assert (out[5:] == 0).all()
    assert (out[2:5] != 0).any()


def test_vectorized_envelope_matches_scalar(fake_backend):
    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    section = vol.read_inline(vol.geometry.inline_min)
    expected = np.stack([np.abs(hilbert(section[i])) for i in range(section.shape[0])])
    np.testing.assert_allclose(out, expected.astype(np.float32), rtol=1e-5)
