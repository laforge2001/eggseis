"""Headless GUI smoke test.

Drives the full M2 workflow:
    open project → list surveys → open one → swap slice axis → swap colormap

Runs under QT_QPA_PLATFORM=offscreen — no display server required.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from eggseis.app import MainWindow


def _find_first_survey_item(tree):
    project_root = tree.topLevelItem(0)
    surveys_group = project_root.child(0)
    return surveys_group.child(0)


def test_open_project_and_swap_slice(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)

    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)

    survey_item = _find_first_survey_item(win.tree)
    assert survey_item is not None, "expected at least one survey under the project"

    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    g = win.section_viewer.geometry
    assert g is not None
    img = win.section_viewer._image.image
    assert img.shape == (g.n_samples, g.n_xlines), (
        f"inline view should be (n_samples={g.n_samples}, n_xlines={g.n_xlines}), "
        f"got {img.shape}"
    )

    win.slice_nav.axis.setCurrentText("xline")
    assert win.section_viewer.current_axis == "xline"
    img = win.section_viewer._image.image
    assert img.shape == (g.n_samples, g.n_inlines)

    win.slice_nav.axis.setCurrentText("timeslice")
    assert win.section_viewer.current_axis == "timeslice"
    img = win.section_viewer._image.image
    assert img.shape == (g.n_inlines, g.n_xlines)

    win.set_colormap("seismic")
    assert win.section_viewer.lut_name == "seismic"

    win.set_colormap("viridis")
    assert win.section_viewer.lut_name == "viridis"


def test_main_window_menus(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)

    bar = win.menuBar()
    titles = [a.text().replace("&", "") for a in bar.actions()]
    assert titles == ["File", "View", "Attribute", "Help"]
    _ = Qt


def test_attribute_menu_lists_builtins(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    names = [a.text() for a in win._attr_group.actions()]
    assert "None (raw amplitude)" in names
    assert "Envelope" in names
    assert "Ormsby Bandpass" in names


def test_apply_envelope_paints_overlay(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)

    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    raw_img = win.section_viewer._image.image.copy()

    win._activate_plugin(envelope._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)

    overlay_img = win.section_viewer._image.image
    g = win.section_viewer.geometry
    assert overlay_img.shape == (g.n_samples, g.n_xlines)
    # envelope is non-negative; raw amplitude is signed → arrays must differ
    assert not (raw_img == overlay_img).all()
    assert (overlay_img >= 0).all()


def test_clear_attribute_restores_raw(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    win._activate_plugin(envelope._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)

    win._activate_plugin(None)
    assert not win.section_viewer.has_overlay


def test_locked_levels_make_gain_visible(qtbot, demo_project_path):
    """With levels locked to the raw slice, multiplying samples changes display."""
    import numpy as np

    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="TestGain")
    def test_gain(trace, k: float = Param(2.0, min=0.0, max=10.0)):
        return (trace * k).astype(np.float32)

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    raw_levels = win.section_viewer._baseline_levels
    assert raw_levels is not None
    raw_low, raw_high = raw_levels
    _ = raw_low  # used implicitly via tuple compare below

    assert win.section_viewer.levels_locked is True
    win._activate_plugin(test_gain._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)

    # Locked: image levels still match raw baseline → gain × 2 visibly differs
    # because the data values are 2× while the LUT mapping is unchanged.
    locked_low, locked_high = win.section_viewer._image.levels
    assert (locked_low, locked_high) == (raw_low, raw_high)


def test_unlocked_levels_recompute_for_overlay(qtbot, demo_project_path):
    import numpy as np

    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="TestGain2")
    def test_gain2(trace, k: float = Param(3.0, min=0.0, max=10.0)):
        return (trace * k).astype(np.float32)

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    win.section_viewer.set_levels_locked(False)
    win._activate_plugin(test_gain2._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)

    # Unlocked: levels recompute from overlay (≈3× raw bounds).
    _raw_low, raw_high = win.section_viewer._baseline_levels
    _over_low, over_high = win.section_viewer._image.levels
    assert abs(over_high) > abs(raw_high) * 1.5


def test_slice_change_recomputes_overlay(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    win._activate_plugin(envelope._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)
    g = win.section_viewer.geometry

    win.slice_nav.axis.setCurrentText("xline")
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay, timeout=2000)
    assert win.section_viewer.current_axis == "xline"
    img = win.section_viewer._image.image
    assert img.shape == (g.n_samples, g.n_inlines)
    assert (img >= 0).all()
