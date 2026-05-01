"""Well path overlay on section viewer."""

from __future__ import annotations

import numpy as np

from eggseis.data import SeismicVolume
from eggseis.data.well import Well


def _vertical_well(surface_xy=(0.0, 0.0)) -> Well:
    md = np.array([0.0, 100.0, 200.0, 300.0], dtype=np.float32)
    deviation = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    return Well(
        name="W1",
        deviation=deviation,
        logs={},
        markers=[],
        surface_xy=surface_xy,
    )


def test_intersect_section_vertical_well_on_inline(fake_backend):
    """Vertical well at (xline=305 in survey coords) on inline section
    returns a single x-pixel column at the well's xline index, multiple y
    points sampling the well's MD range."""

    geom = fake_backend.geometry
    # Well surface located at survey-coord (xline=305).
    # Inline coord doesn't matter for an inline section unless we filter by
    # slice slab — but a vertical well only intersects ONE inline. Tests
    # the slab tolerance separately below.
    well = _vertical_well(surface_xy=(305.0, geom.inline_min))
    pts = well.intersect_section(axis="inline", index=geom.inline_min, geometry=geom)
    assert pts.ndim == 2 and pts.shape[1] == 2
    # All x_pixels point at xline 305's column index.
    expected_x = (305 - geom.xline_min) // geom.xline_step
    np.testing.assert_array_equal(pts[:, 0], expected_x)


def test_intersect_section_misses_off_inline(fake_backend):
    """Vertical well at inline 999 doesn't intersect inline section at 100."""
    geom = fake_backend.geometry
    well = _vertical_well(surface_xy=(305.0, geom.inline_min + 999))
    pts = well.intersect_section(axis="inline", index=geom.inline_min, geometry=geom)
    assert pts.size == 0


def test_section_viewer_add_remove_well(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    well = _vertical_well(surface_xy=(305.0, vol.geometry.inline_min))

    viewer.add_well_overlay(well)
    assert viewer.well_count() == 1

    viewer.remove_well_overlay(well.name)
    assert viewer.well_count() == 0


def test_well_overlay_updates_on_slice_change(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    viewer.add_well_overlay(_vertical_well(surface_xy=(305.0, vol.geometry.inline_min)))

    viewer.show_slice("xline", vol.geometry.xline_min)
    assert viewer.well_count() == 1
