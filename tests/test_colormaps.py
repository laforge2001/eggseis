"""Tests for colormap LUTs."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.colormaps import LUTS_AVAILABLE, get_lut


@pytest.mark.parametrize("name", LUTS_AVAILABLE)
def test_lut_shape_and_dtype(name: str) -> None:
    lut = get_lut(name)
    assert lut.shape == (256, 4)
    assert lut.dtype == np.uint8
    assert np.all(lut[:, 3] == 255)  # alpha solid


def test_seismic_white_at_center() -> None:
    lut = get_lut("seismic")
    r, g, b, _ = lut[127]
    assert r > 240 and g > 240 and b > 240


def test_gray_is_monotonic() -> None:
    lut = get_lut("gray")
    assert np.all(np.diff(lut[:, 0]) >= 0)


def test_unknown_lut_raises() -> None:
    with pytest.raises(KeyError):
        get_lut("does-not-exist")


def test_lut_is_cached() -> None:
    a = get_lut("viridis")
    b = get_lut("viridis")
    assert a is b


def test_vik_is_diverging_white_at_center() -> None:
    lut = get_lut("vik")
    r, g, b, _ = lut[127]
    assert r > 200 and g > 200 and b > 200  # near-white at midpoint


def test_batlow_endpoints_distinct() -> None:
    lut = get_lut("batlow")
    assert tuple(lut[0, :3]) != tuple(lut[-1, :3])
    # batlow is sequential; endpoints must differ in luminance significantly
    lo = int(lut[0, :3].mean())
    hi = int(lut[-1, :3].mean())
    assert abs(hi - lo) > 80


def test_default_amplitude_and_attribute_constants() -> None:
    from eggseis.colormaps import DEFAULT_AMPLITUDE, DEFAULT_ATTRIBUTE

    assert DEFAULT_AMPLITUDE in LUTS_AVAILABLE
    assert DEFAULT_ATTRIBUTE in LUTS_AVAILABLE


def test_cmcrameri_missing_fallback(monkeypatch) -> None:
    """If cmcrameri is unavailable, vik/batlow fall back to seismic/viridis."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name.startswith("cmcrameri"):
            raise ImportError("simulated missing")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Force re-resolution by clearing the cache for these names.
    from eggseis import colormaps

    colormaps._CACHE.pop("vik", None)
    lut = colormaps.get_lut("vik")
    assert lut.shape == (256, 4)
