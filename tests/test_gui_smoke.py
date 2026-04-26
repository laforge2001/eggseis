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
