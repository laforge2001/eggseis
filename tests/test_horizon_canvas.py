"""GraphCanvas integration for horizon nodes + dashed Source line."""

from __future__ import annotations

import pytest

from eggseis.graph.model import Graph

qtpynodeeditor = pytest.importorskip("qtpynodeeditor")


@pytest.fixture
def canvas(qtbot):
    from eggseis.graph.canvas import GraphCanvas

    widget = GraphCanvas()
    qtbot.addWidget(widget)
    return widget


def test_add_horizon_node_spawns_scene_node_and_dashed_line(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top_reservoir", pos=(150.0, 75.0))
    assert nid in g.nodes
    assert canvas.horizon_scene_node_for(nid) is not None
    line = canvas.dashed_line_for(nid)
    assert line is not None


def test_remove_horizon_node_removes_dashed_line(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.remove_node(nid)
    assert canvas.dashed_line_for(nid) is None


def test_dashed_line_endpoints_update_on_node_move(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top", pos=(100.0, 50.0))
    line = canvas.dashed_line_for(nid)
    line_p1 = (line.line().p1().x(), line.line().p1().y())

    horizon_scene = canvas.horizon_scene_node_for(nid)
    horizon_scene.position = (300.0, 200.0)
    canvas._refresh_dashed_lines()
    new_p1 = (line.line().p1().x(), line.line().p1().y())
    assert new_p1 != line_p1


def test_canvas_register_horizons_populates_add_horizon_submenu(canvas):
    """register_horizons makes names available for the Add Horizon submenu."""
    g = Graph()
    canvas.bind(g)
    canvas.register_horizons(["top", "base", "channel"])
    names = canvas.horizon_names_available()
    assert names == ["top", "base", "channel"]


def test_register_horizons_empty_list_clears(canvas):
    g = Graph()
    canvas.bind(g)
    canvas.register_horizons(["top"])
    canvas.register_horizons([])
    assert canvas.horizon_names_available() == []


def test_pin_and_unpin_via_canvas_methods(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.set_horizon_pinned(nid, False)
    assert nid not in g.pinned_overlays
    canvas.set_horizon_pinned(nid, True)
    assert nid in g.pinned_overlays


def test_set_horizon_pinned_emits_overlay_changed_signal(canvas, qtbot):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")

    received = []
    canvas.overlayChanged.connect(received.append)
    canvas.set_horizon_pinned(nid, False)
    assert received == [nid]
