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


def test_horizon_model_hidden_from_lib_right_click_menu(canvas):
    """The lib's 'Add Node' menu groups by registered category. _HorizonModel
    must NOT appear there — adding it through the lib menu produces an
    unusable disconnected horizon node with no associated horizon name.

    The fix: register the model so scene.create_node still works, but drop
    it from the registry's category-association map (which the menu reads).
    """
    cat_map = canvas._registry.registered_models_category_association()
    assert "Horizon" not in cat_map, (
        "Horizon should be hidden from the lib's right-click 'Add Node' menu"
    )
    # And scene.create_node(_HorizonModel) must still succeed (used by
    # add_horizon_node) — exercise it indirectly via the public path.
    from eggseis.graph.model import Graph

    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("h1")
    assert nid in g.nodes


def test_scene_node_to_graph_id_resolves_horizon_scene_node(canvas):
    """Right-click context-menu lookup must walk _horizon_scene_nodes too."""
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    horizon_scene = canvas.horizon_scene_node_for(nid)
    assert canvas._scene_node_to_graph_id(horizon_scene) == nid


def test_disconnect_horizon_removes_association_and_line(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    assert canvas.dashed_line_for(nid) is not None
    assert canvas.is_horizon_connected(nid)
    canvas.disconnect_horizon(nid)
    assert canvas.dashed_line_for(nid) is None
    assert not canvas.is_horizon_connected(nid)
    assert all(a.horizon_node_id != nid for a in g.associations)
    # Node is still on the canvas.
    assert nid in g.nodes


def test_reconnect_horizon_restores_line_and_association(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.disconnect_horizon(nid)
    canvas.connect_horizon(nid)
    assert canvas.dashed_line_for(nid) is not None
    assert canvas.is_horizon_connected(nid)
    assert any(a.horizon_node_id == nid for a in g.associations)


def test_disconnected_horizon_not_in_visible_horizons_for_tap(canvas):
    """Pinned but disconnected → not visible (no Source association)."""
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.disconnect_horizon(nid)
    # Still pinned, but no association.
    assert nid in g.pinned_overlays
    visible = g.visible_horizons_for_tap(*g.tap_port)
    assert nid not in visible


def test_delete_key_path_removes_horizon(canvas):
    """Lib's delete_selection action emits node_deleted; canvas must
    mirror that into Graph state for horizon nodes (not just plugins)."""
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    scene_node = canvas.horizon_scene_node_for(nid)
    assert scene_node is not None

    # Simulate the lib's delete path: emit node_deleted ourselves.
    canvas._scene.node_deleted.emit(scene_node)

    assert nid not in g.nodes
    assert g.associations == []
    assert nid not in g.pinned_overlays
    assert canvas.dashed_line_for(nid) is None
    assert canvas.horizon_scene_node_for(nid) is None
