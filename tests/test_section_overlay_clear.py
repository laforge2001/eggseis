"""SectionViewer.set_volume should clear well + horizon overlay state."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")


def test_set_volume_clears_well_overlays(qtbot, fake_backend):
    from eggseis.data import SeismicVolume
    from eggseis.data.well import Well
    from eggseis.viewers.section import SectionViewer

    sv = SectionViewer()
    qtbot.addWidget(sv)
    vol_a = SeismicVolume(fake_backend)
    sv.set_volume(vol_a)

    well = Well(
        name="WX",
        deviation=np.array([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]], dtype=np.float32),
        logs={"GR": np.array([1.0, 2.0], dtype=np.float32)},
        markers=[],
        surface_xy=(310.0, 110.0),
    )
    sv.add_well_overlay(well)
    assert "WX" in sv._well_overlays

    sv.set_volume(vol_a)  # rebind same volume
    assert sv._well_overlays == {}
    assert sv._horizon_overlays == {}
