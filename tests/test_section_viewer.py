"""Section viewer overlay behaviour. Headless via QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from eggseis.data import SeismicVolume
from eggseis.viewers.section import SectionViewer


def test_partial_overlay_keeps_baseline_levels(qtbot, fake_backend):
    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    viewer._render()  # internal hook used in test
    baseline = viewer._baseline_levels
    assert baseline is not None

    arr = np.zeros((vol.geometry.n_xlines, vol.geometry.n_samples), dtype=np.float32)
    viewer.set_overlay(arr, partial=True)
    assert viewer._baseline_levels == baseline
