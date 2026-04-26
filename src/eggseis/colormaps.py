"""Named lookup tables (LUTs) for the section viewer.

Each LUT is a (256, 4) uint8 array of RGBA values. Built lazily and cached.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

LUTS_AVAILABLE: tuple[str, ...] = ("gray", "seismic", "viridis")


def _build_gray() -> np.ndarray:
    g = np.linspace(0, 255, 256, dtype=np.uint8)
    return np.stack([g, g, g, np.full_like(g, 255)], axis=1)


def _build_seismic() -> np.ndarray:
    """Red-white-blue, white at center. Common seismic amplitude convention."""
    n = 256
    half = n // 2
    out = np.zeros((n, 4), dtype=np.uint8)
    out[:, 3] = 255
    out[:half, 0] = np.linspace(0, 255, half)
    out[:half, 1] = np.linspace(0, 255, half)
    out[:half, 2] = 255
    out[half:, 0] = 255
    out[half:, 1] = np.linspace(255, 0, n - half)
    out[half:, 2] = np.linspace(255, 0, n - half)
    return out


_VIRIDIS_NODES_T = np.array([0.00, 0.14, 0.29, 0.43, 0.57, 0.71, 0.86, 1.00])
_VIRIDIS_NODES_RGB = np.array(
    [
        [0.267, 0.005, 0.329],
        [0.282, 0.140, 0.458],
        [0.254, 0.265, 0.530],
        [0.207, 0.372, 0.553],
        [0.164, 0.471, 0.558],
        [0.135, 0.567, 0.546],
        [0.213, 0.726, 0.422],
        [0.993, 0.906, 0.144],
    ]
)


def _build_viridis() -> np.ndarray:
    """Piecewise-linear viridis approximation (no matplotlib dependency)."""
    t = np.linspace(0.0, 1.0, 256)
    rgb = np.empty((256, 3))
    for ch in range(3):
        rgb[:, ch] = np.interp(t, _VIRIDIS_NODES_T, _VIRIDIS_NODES_RGB[:, ch])
    out = np.zeros((256, 4), dtype=np.uint8)
    out[:, :3] = (rgb * 255).astype(np.uint8)
    out[:, 3] = 255
    return out


_BUILDERS: dict[str, Callable[[], np.ndarray]] = {
    "gray": _build_gray,
    "seismic": _build_seismic,
    "viridis": _build_viridis,
}

_CACHE: dict[str, np.ndarray] = {}


def get_lut(name: str) -> np.ndarray:
    if name not in _BUILDERS:
        raise KeyError(f"Unknown colormap {name!r}; available: {LUTS_AVAILABLE}")
    if name not in _CACHE:
        _CACHE[name] = _BUILDERS[name]()
    return _CACHE[name]
