"""Horizon overlay math + pyqtgraph polyline item.

Pure-numpy helpers for converting Horizon grids into (x_pixel, y_pixel)
polyline points, where pixel coords match the SectionViewer's ImageItem:
the x axis is the cross-axis index (xlines for inline sections, inlines
for xline sections) and y is the time-sample index.

The horizon's own (inline_min, xline_min, *_step) describe its grid
extent, which may be smaller than the survey's geometry (e.g. an
auto-detected horizon covering only a sub-region). The helpers map each
horizon cell back to the survey's pixel coordinates and only emit
points where the horizon and the survey overlap.
"""

from __future__ import annotations

import numpy as np

from eggseis.data import SurveyGeometry
from eggseis.data.horizon import Horizon


def inline_polyline_points(
    horizon: Horizon, geometry: SurveyGeometry, inline: int
) -> np.ndarray:
    """Polyline points for an inline section at survey-coord `inline`.

    Returns shape `(n_h_xlines, 2)` of `(x_pixel, y_pixel)` — one entry
    per horizon column on the requested inline. NaN horizon samples
    produce NaN y so pyqtgraph treats them as gaps.
    """
    i = (inline - horizon.inline_min) // (horizon.inline_step or 1)
    if not (0 <= i < horizon.grid.shape[0]):
        return np.empty((0, 2), dtype=np.float32)
    times = horizon.grid[i, :]
    y = (times / geometry.sample_rate_ms).astype(np.float32)
    n_h_xlines = horizon.grid.shape[1]
    h_xlines = horizon.xline_min + np.arange(n_h_xlines) * (horizon.xline_step or 1)
    x = ((h_xlines - geometry.xline_min) // (geometry.xline_step or 1)).astype(np.float32)
    return np.column_stack([x, y])


def xline_polyline_points(
    horizon: Horizon, geometry: SurveyGeometry, xline: int
) -> np.ndarray:
    """Polyline points for an xline section at survey-coord `xline`.

    Returns shape `(n_h_inlines, 2)` of `(x_pixel, y_pixel)`.
    """
    j = (xline - horizon.xline_min) // (horizon.xline_step or 1)
    if not (0 <= j < horizon.grid.shape[1]):
        return np.empty((0, 2), dtype=np.float32)
    times = horizon.grid[:, j]
    y = (times / geometry.sample_rate_ms).astype(np.float32)
    n_h_inlines = horizon.grid.shape[0]
    h_inlines = horizon.inline_min + np.arange(n_h_inlines) * (horizon.inline_step or 1)
    x = ((h_inlines - geometry.inline_min) // (geometry.inline_step or 1)).astype(np.float32)
    return np.column_stack([x, y])
