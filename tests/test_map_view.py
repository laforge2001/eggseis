"""MapViewWidget: top-down plan view with current-slice indicator."""

from __future__ import annotations

import numpy as np

from eggseis.data import SeismicVolume


def test_map_view_construction(qtbot):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    # No volume yet → outline is empty.
    x, _y = w._outline.getData()
    assert x is None or len(x) == 0


def test_map_view_set_volume_draws_outline(qtbot, fake_backend):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    vol = SeismicVolume(fake_backend)
    w.set_volume(vol)

    x, y = w._outline.getData()
    g = vol.geometry
    # Closed rectangle: 5 vertices.
    assert len(x) == 5
    assert len(y) == 5
    assert min(x) == g.xline_min
    assert max(x) == g.xline_min + g.n_xlines * g.xline_step
    assert min(y) == g.inline_min
    assert max(y) == g.inline_min + g.n_inlines * g.inline_step


def test_map_view_inline_indicator_y_matches_index(qtbot, fake_backend):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    vol = SeismicVolume(fake_backend)
    w.set_volume(vol)

    target = vol.geometry.inline_min + 3
    w.show_slice("inline", target)
    x, y = w._slice_indicator.getData()
    np.testing.assert_array_equal(y, [target, target])
    # Spans full xline range.
    g = vol.geometry
    assert min(x) == g.xline_min
    assert max(x) == g.xline_min + g.n_xlines * g.xline_step


def test_map_view_xline_indicator_x_matches_index(qtbot, fake_backend):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    vol = SeismicVolume(fake_backend)
    w.set_volume(vol)

    target = vol.geometry.xline_min + 5
    w.show_slice("xline", target)
    x, y = w._slice_indicator.getData()
    np.testing.assert_array_equal(x, [target, target])
    g = vol.geometry
    assert min(y) == g.inline_min
    assert max(y) == g.inline_min + g.n_inlines * g.inline_step


def test_map_view_timeslice_clears_indicator(qtbot, fake_backend):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    vol = SeismicVolume(fake_backend)
    w.set_volume(vol)
    # Seed an inline indicator first.
    w.show_slice("inline", vol.geometry.inline_min + 1)
    # Then switch to timeslice — indicator data should clear.
    w.show_slice("timeslice", 4)
    x, _ = w._slice_indicator.getData()
    assert x is None or len(x) == 0


def test_map_view_show_slice_without_volume_is_safe(qtbot):
    from eggseis.viewers.map_view import MapViewWidget

    w = MapViewWidget()
    qtbot.addWidget(w)
    w.show_slice("inline", 0)  # must not raise
