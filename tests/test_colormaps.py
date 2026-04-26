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
