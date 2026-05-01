"""Horizon overlay rendered as a polyline on the section viewer."""

from __future__ import annotations

import numpy as np

from eggseis.data import SeismicVolume
from eggseis.data.horizon import Horizon


def _horizon_for(geom, value: float = 60.0) -> Horizon:
    grid = np.full((geom.n_inlines, geom.n_xlines), value, dtype=np.float32)
    return Horizon(
        name="top",
        grid=grid,
        geometry_ref="x",
        inline_min=geom.inline_min,
        xline_min=geom.xline_min,
        inline_step=geom.inline_step,
        xline_step=geom.xline_step,
    )


def test_inline_polyline_for_constant_horizon(fake_backend):
    """Constant horizon at 60 ms on an inline section: polyline is a flat
    line at the corresponding row index across all xlines."""
    from eggseis.viewers.horizon_overlay import inline_polyline_points

    vol = SeismicVolume(fake_backend)
    h = _horizon_for(vol.geometry, value=60.0)
    pts = inline_polyline_points(h, vol.geometry, inline=vol.geometry.inline_min)

    # Returned shape: (n_xlines, 2) of (x_pixel, y_pixel) where x_pixel is
    # the xline index and y_pixel is the time-sample index.
    assert pts.shape == (vol.geometry.n_xlines, 2)
    expected_y = 60.0 / vol.geometry.sample_rate_ms
    np.testing.assert_allclose(pts[:, 1], expected_y, atol=1e-3)
    np.testing.assert_array_equal(pts[:, 0], np.arange(vol.geometry.n_xlines))


def test_xline_polyline_for_constant_horizon(fake_backend):
    from eggseis.viewers.horizon_overlay import xline_polyline_points

    vol = SeismicVolume(fake_backend)
    h = _horizon_for(vol.geometry, value=60.0)
    pts = xline_polyline_points(h, vol.geometry, xline=vol.geometry.xline_min)

    assert pts.shape == (vol.geometry.n_inlines, 2)


def test_polyline_skips_nan_samples(fake_backend):
    from eggseis.viewers.horizon_overlay import inline_polyline_points

    vol = SeismicVolume(fake_backend)
    h = _horizon_for(vol.geometry, value=60.0)
    h.grid[0, 2] = np.nan
    pts = inline_polyline_points(h, vol.geometry, inline=vol.geometry.inline_min)
    # NaN samples produce NaN y; pyqtgraph treats those as gaps.
    assert np.isnan(pts[2, 1])
    assert not np.isnan(pts[0, 1])


def test_section_viewer_add_remove_horizon(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    h = _horizon_for(vol.geometry)

    viewer.add_horizon_overlay(h)
    assert viewer.horizon_count() == 1

    viewer.remove_horizon_overlay(h.name)
    assert viewer.horizon_count() == 0


def test_section_viewer_horizon_updates_on_slice_change(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    viewer.add_horizon_overlay(_horizon_for(vol.geometry))

    # Switch to xline; overlay should re-render without crashing.
    viewer.show_slice("xline", vol.geometry.xline_min)
    assert viewer.horizon_count() == 1

    # And to timeslice (no overlay drawn for timeslice, but no crash).
    viewer.show_slice("timeslice", 0)
    assert viewer.horizon_count() == 1


def test_unknown_horizon_remove_is_noop(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    viewer.set_volume(SeismicVolume(fake_backend))
    viewer.remove_horizon_overlay("nope")  # silently ignored
    assert viewer.horizon_count() == 0
