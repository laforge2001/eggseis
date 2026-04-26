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
    assert titles == ["File", "View", "Help"]
    _ = Qt
