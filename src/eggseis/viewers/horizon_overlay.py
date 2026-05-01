"""Horizon overlay math + pyqtgraph polyline item.

Pure-numpy helpers for converting Horizon grids into (x_pixel, y_pixel)
polyline points, where pixel coords match the SectionViewer's ImageItem:
the x axis is the cross-axis index (xlines for inline sections, inlines
for xline sections) and y is the time-sample index.
"""

from __future__ import annotations

import numpy as np

from eggseis.data import SurveyGeometry
from eggseis.data.horizon import Horizon


def inline_polyline_points(
    horizon: Horizon, geometry: SurveyGeometry, inline: int
) -> np.ndarray:
    """Polyline points for an inline section at survey-coord `inline`.

    Returns shape `(n_xlines, 2)` of `(x_pixel, y_pixel)`. NaN horizon
    samples produce NaN y so pyqtgraph treats them as gaps.
    """
    i = (inline - geometry.inline_min) // geometry.inline_step
    if not (0 <= i < horizon.grid.shape[0]):
        return np.empty((0, 2), dtype=np.float32)
    times = horizon.grid[i, :]
    y = times / geometry.sample_rate_ms
    x = np.arange(geometry.n_xlines, dtype=np.float32)
    return np.column_stack([x, y])


def xline_polyline_points(
    horizon: Horizon, geometry: SurveyGeometry, xline: int
) -> np.ndarray:
    j = (xline - geometry.xline_min) // geometry.xline_step
    if not (0 <= j < horizon.grid.shape[1]):
        return np.empty((0, 2), dtype=np.float32)
    times = horizon.grid[:, j]
    y = times / geometry.sample_rate_ms
    x = np.arange(geometry.n_inlines, dtype=np.float32)
    return np.column_stack([x, y])
