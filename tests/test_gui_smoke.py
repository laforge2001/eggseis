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
    assert titles == ["File", "View", "Survey", "Graph", "Attribute", "Help"]
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


def test_help_plugin_errors_action_disabled_when_clean(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    # No broken plugins in default state → action exists but is disabled.
    assert hasattr(win, "_plugin_errors_action")
    assert win._plugin_errors_action.isEnabled() == bool(win._plugin_load_errors)


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


def test_attribute_apply_via_orchestrator(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)

    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    with qtbot.waitSignal(win._compute.sectionReady, timeout=10_000):
        win._activate_plugin(envelope._eggseis_spec)

    assert win.section_viewer.has_overlay


def test_compute_errors_menu_lists_failures(qtbot, demo_project_path):
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Boom", version="0.1.0")
    def boom(trace, k: float = Param(1.0)):
        raise RuntimeError("boom")

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)

    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    with qtbot.waitSignal(win._compute.failed, timeout=5000):
        win._activate_plugin(boom._eggseis_spec)

    assert any("boom" in msg for _name, msg in win._compute_errors)
    clear_registry()


def test_slice_change_preserves_active_params(qtbot, demo_project_path):
    """Dragging a slider then switching slices must reuse the dragged value, not defaults."""
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    with qtbot.waitSignal(win._compute.sectionReady, timeout=10_000):
        win._activate_plugin(envelope._eggseis_spec)
    assert win._active_params is not None
    snapshot = win._active_params

    # Step the slice; orchestrator should be called with the snapshot params.
    g = win.section_viewer.geometry
    new_index = g.inline_min + 1 if win.section_viewer.current_axis == "inline" else g.xline_min + 1
    with qtbot.waitSignal(win._compute.sectionReady, timeout=10_000):
        win._on_slice_changed(win.section_viewer.current_axis, new_index)
    # _active_params is unchanged after the slice change
    assert win._active_params is snapshot


def test_graph_chain_three_attributes_tap_each(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope
    from eggseis.builtins.ormsby_bandpass import ormsby_bandpass
    from eggseis.builtins.rms_amplitude import rms_amplitude
    from eggseis.graph.model import SOURCE_ID, Edge

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    canvas = win._canvas
    a = canvas.add_plugin(ormsby_bandpass._eggseis_spec)
    b = canvas.add_plugin(envelope._eggseis_spec)
    c = canvas.add_plugin(rms_amplitude._eggseis_spec)

    canvas.connect_edge(Edge(SOURCE_ID, "inline", a, "trace"))
    canvas.connect_edge(Edge(a, "out", b, "trace"))
    canvas.connect_edge(Edge(b, "out", c, "trace"))

    graph = win._graphs[win._active_survey_id]
    assert len(graph.nodes) == 3

    for node_id in (a, b, c):
        with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
            canvas.set_tap(node_id, "out")
        assert win.section_viewer.has_overlay


def test_graph_menu_adds_node_to_canvas(qtbot, demo_project_path):
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    # Empty graph initially.
    g = win._graphs[win._active_survey_id]
    assert len(g.nodes) == 0

    win.add_plugin_to_graph(envelope._eggseis_spec)
    assert len(g.nodes) == 1
    only = next(iter(g.nodes.values()))
    assert only.spec.id == envelope._eggseis_spec.id


def test_graph_menu_action_exists(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    actions = {a.text().replace("&", ""): a for a in win.menuBar().actions()}
    assert "Graph" in actions, f"expected Graph menu, got {list(actions)}"


def test_graph_subtract_tap_ready(qtbot, demo_project_path):
    """Multi-input subtract: a→sub.a, source→sub.b. Tap sub.out."""
    from eggseis.builtins.envelope import envelope
    from eggseis.builtins.subtract import subtract
    from eggseis.graph.model import SOURCE_ID, Edge

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    canvas = win._canvas
    env = canvas.add_plugin(envelope._eggseis_spec)
    sub = canvas.add_plugin(subtract._eggseis_spec)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", env, "trace"))
    canvas.connect_edge(Edge(env, "out", sub, "a"))
    canvas.connect_edge(Edge(SOURCE_ID, "inline", sub, "b"))

    with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
        canvas.set_tap(sub, "out")
    assert win.section_viewer.has_overlay


def test_pin_unpin_horizon_node_updates_section_viewer(qtbot, demo_project_path):
    """Adding a horizon node + pinning shows overlay; unpinning removes it."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    # Synthetic horizon registered into the project for this test.
    import numpy as np

    from eggseis.data.horizon import Horizon
    geom = win.section_viewer.geometry
    grid = np.full((geom.n_inlines, geom.n_xlines), 50.0, dtype=np.float32)
    h = Horizon(name="test_top", grid=grid, geometry_ref="x")
    target = win._project.root / "horizons" / "test_top"
    h.save(target)

    from eggseis.project import HorizonEntry
    win._project = win._project.with_horizon_added(
        HorizonEntry(name="test_top", path=target)
    )
    win._canvas.register_horizons([h.name for h in win._project.horizons])

    nid = win._canvas.add_horizon_node("test_top")
    qtbot.wait(50)  # let signal-driven sync run
    assert "test_top" in win.section_viewer.horizon_overlay_names()

    win._canvas.set_horizon_pinned(nid, False)
    qtbot.wait(50)
    assert "test_top" not in win.section_viewer.horizon_overlay_names()


def test_double_click_well_in_tree_loads_into_viewer(qtbot, demo_project_path):
    """Double-click on a well item in the tree adds it to the section viewer
    and populates the log panel."""
    import numpy as np

    from eggseis.data.well import Well
    from eggseis.project import WellEntry

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    # Add a synthetic well to the project + save to disk.
    md = np.linspace(0.0, 200.0, 5, dtype=np.float32)
    dev = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    well = Well(
        name="WTEST",
        deviation=dev,
        logs={"GR": np.array([55.0, 60.0, 65.0, 70.0, 75.0], dtype=np.float32)},
        markers=[],
        surface_xy=(0.0, 0.0),
    )
    target = win._project.root / "wells" / "WTEST.h5"
    well.save(target)
    win._project = win._project.with_well_added(WellEntry(name="WTEST", path=target))
    win.tree.set_project(win._project)

    # Find the new well item under the Wells category.
    project_root = win.tree.topLevelItem(0)
    wells_group = project_root.child(2)  # 0=Surveys, 1=Horizons, 2=Wells
    assert wells_group.text(0) == "Wells"
    well_item = None
    for i in range(wells_group.childCount()):
        if wells_group.child(i).text(0) == "WTEST":
            well_item = wells_group.child(i)
            break
    assert well_item is not None

    win.tree.itemDoubleClicked.emit(well_item, 0)
    qtbot.wait(50)
    assert "WTEST" in win.section_viewer._well_overlays
    assert win.well_log_panel.selected_curve() == "GR"


def test_open_project_auto_opens_active_survey(qtbot, demo_project_path):
    """Opening a project that has a saved active_survey re-opens it
    and applies viewer state without explicit user action."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    # Manually open survey + save with viewer state.
    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)
    win.section_viewer.show_slice("xline", win.section_viewer.geometry.xline_min + 5)
    win.set_colormap("seismic")
    # _on_save_project requires a graph + active_survey to set graph_dict.
    # The graph already has active_survey wired through open_survey, so just save.
    win._on_save_project()
    qtbot.wait(50)

    # Re-open in a fresh window.
    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win2.section_viewer.has_volume, timeout=2000)
    assert win2.section_viewer.current_axis == "xline"
    assert win2.section_viewer.lut_name == "seismic"


def test_open_project_restores_loaded_wells(qtbot, demo_project_path):
    """If a project saved with open_wells, those wells reappear on load."""
    import numpy as np

    from eggseis.data.well import Well
    from eggseis.project import WellEntry

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    # Synthesise + persist a well, register in project, save.
    md = np.linspace(0.0, 100.0, 3, dtype=np.float32)
    dev = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    well = Well(name="WX", deviation=dev, logs={"GR": md.copy()}, markers=[], surface_xy=(0.0, 0.0))
    target = win._project.root / "wells" / "WX.h5"
    well.save(target)
    win._project = win._project.with_well_added(WellEntry(name="WX", path=target))
    win.section_viewer.add_well_overlay(well)
    win._on_save_project()
    qtbot.wait(50)

    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win2.section_viewer.has_volume, timeout=2000)
    qtbot.wait(50)  # let restore handlers run
    assert "WX" in win2.section_viewer._well_overlays


def test_well_load_auto_snaps_section_to_well_inline(qtbot, demo_project_path):
    """Loading a well jumps the section to that well's inline."""
    import numpy as np

    from eggseis.data.well import Well
    from eggseis.project import WellEntry

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    win.tree.itemDoubleClicked.emit(_find_first_survey_item(win.tree), 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    geom = win.section_viewer.geometry
    target_inline = geom.inline_min + 5
    md = np.array([0.0, 100.0, 200.0], dtype=np.float32)
    dev = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    well = Well(
        name="SNAP",
        deviation=dev,
        logs={"GR": np.array([55.0, 60.0, 65.0], dtype=np.float32)},
        markers=[],
        surface_xy=(geom.xline_min + 3.0, float(target_inline)),
    )
    target = win._project.root / "wells" / "SNAP.h5"
    well.save(target)
    win._project = win._project.with_well_added(WellEntry(name="SNAP", path=target))
    win.tree.set_project(win._project)

    # Trigger via tree double-click.
    project_root = win.tree.topLevelItem(0)
    wells_group = project_root.child(2)
    well_item = None
    for i in range(wells_group.childCount()):
        if wells_group.child(i).text(0) == "SNAP":
            well_item = wells_group.child(i)
            break
    assert well_item is not None
    win.tree.itemDoubleClicked.emit(well_item, 0)
    qtbot.wait(50)

    assert win.section_viewer.current_axis == "inline"
    assert win.section_viewer.current_index == target_inline
    assert "SNAP" in win.map_view._well_marker_items
