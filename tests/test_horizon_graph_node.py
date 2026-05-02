"""Horizon node Graph integration."""

from __future__ import annotations

import pytest

from eggseis.graph.model import SOURCE_ID, Graph, Node, OrphanHorizonError


def test_node_defaults_to_plugin_kind(linear_spec):
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n.kind == "plugin"
    assert n.horizon_name is None


def test_horizon_node_construction():
    n = Node(
        spec=None, params=None,
        kind="horizon", horizon_name="top_reservoir",
    )
    assert n.kind == "horizon"
    assert n.horizon_name == "top_reservoir"
    assert n.spec is None


def test_plugin_node_without_spec_raises():
    with pytest.raises(ValueError, match="plugin nodes require a spec"):
        Node(spec=None, params=None, kind="plugin")


def test_horizon_node_without_horizon_name_raises():
    with pytest.raises(ValueError, match="horizon_name"):
        Node(spec=None, params=None, kind="horizon")


def test_horizon_node_with_spec_raises(linear_spec):
    with pytest.raises(ValueError, match="must not set spec"):
        Node(spec=linear_spec, params=None, kind="horizon", horizon_name="x")


def test_plugin_node_with_horizon_name_raises(linear_spec):
    with pytest.raises(ValueError, match="must not set horizon_name"):
        Node(spec=linear_spec, params=linear_spec.param_model(), kind="plugin", horizon_name="x")


def test_add_horizon_node_creates_association_and_pins():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top_reservoir", pos=(100.0, 50.0))
    assert nid in g.nodes
    assert g.nodes[nid].kind == "horizon"
    assert g.nodes[nid].horizon_name == "top_reservoir"
    assert any(
        a.horizon_node_id == nid and a.source_node_id == SOURCE_ID
        for a in g.associations
    )
    assert nid in g.pinned_overlays


def test_remove_horizon_node_drops_association_and_pin():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    g.remove_node(nid)
    assert nid not in g.nodes
    assert g.associations == []
    assert g.pinned_overlays == set()


def test_pin_unpin_overlay():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    g.unpin_overlay(nid)
    assert nid not in g.pinned_overlays
    g.pin_overlay(nid)
    assert nid in g.pinned_overlays


def test_pin_overlay_rejects_plugin_node(linear_spec):
    from eggseis.graph.model import Node
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    with pytest.raises(ValueError, match="horizon"):
        g.pin_overlay(n.node_id)


def test_undo_after_add_horizon_node_removes_it():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    assert nid in g.nodes
    g.undo()
    assert nid not in g.nodes
    assert g.associations == []
    assert g.pinned_overlays == set()


def test_undo_after_remove_horizon_restores_association_and_pin():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    g.remove_node(nid)
    g.undo()
    assert nid in g.nodes
    assert any(a.horizon_node_id == nid for a in g.associations)
    assert nid in g.pinned_overlays


def test_unpin_overlay_unknown_id_is_silent():
    g = Graph()
    g.unpin_overlay("nonexistent-id")  # must not raise


def test_visible_horizons_for_tap_when_source_in_cone(linear_spec):
    """v1.0: every pinned horizon is visible because Source is always in the cone."""
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    from eggseis.graph.model import Edge
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    g.set_tap(n.node_id)
    h = g.add_horizon_node(horizon_name="top")
    assert g.visible_horizons_for_tap(*g.tap_port) == [h]


def test_visible_horizons_for_tap_excludes_unpinned():
    g = Graph()
    h = g.add_horizon_node(horizon_name="top")
    g.unpin_overlay(h)
    assert g.visible_horizons_for_tap(*g.tap_port) == []


def test_horizon_node_excluded_from_upstream_cone(linear_spec):
    """Horizon nodes must not appear in upstream_cone results."""
    from eggseis.graph.model import Edge
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    h = g.add_horizon_node(horizon_name="top")
    cone = g.upstream_cone(n.node_id, "out")
    assert h not in cone


def test_horizon_node_serialises_with_kind_and_name():
    g = Graph()
    g.add_horizon_node(horizon_name="top_reservoir", pos=(120.0, 50.0))
    d = g.to_dict()
    horizon_dicts = [n for n in d["nodes"] if n.get("kind") == "horizon"]
    assert len(horizon_dicts) == 1
    assert horizon_dicts[0]["horizon_name"] == "top_reservoir"
    assert horizon_dicts[0]["pos"] == [120.0, 50.0]


def test_associations_and_pinned_overlays_round_trip(linear_spec):
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    d = g.to_dict()
    assert d["associations"] == [{"horizon_node_id": nid, "source_node_id": SOURCE_ID}]
    assert d["pinned_overlays"] == [nid]


def test_from_dict_reconstructs_horizon_node(linear_spec):
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    d = g.to_dict()
    plugins = {linear_spec.id: linear_spec}
    horizons = {"top": object()}  # any sentinel; from_dict only checks membership
    rebuilt = Graph.from_dict(d, plugins=plugins, horizons=horizons)
    assert rebuilt.nodes[nid].kind == "horizon"
    assert rebuilt.nodes[nid].horizon_name == "top"
    assert rebuilt.pinned_overlays == {nid}


def test_orphan_horizon_on_load_raises(linear_spec):
    g = Graph()
    g.add_horizon_node(horizon_name="missing")
    d = g.to_dict()
    with pytest.raises(OrphanHorizonError, match="missing"):
        Graph.from_dict(d, plugins={linear_spec.id: linear_spec}, horizons={})


def test_from_dict_round_trip_with_mixed_graph(linear_spec):
    """Round-trip a graph carrying plugin nodes + edges + horizon nodes
    + associations + pinned overlays. Everything survives."""
    from eggseis.graph.model import Edge

    g = Graph()
    plugin_node = Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0))
    g.add_node(plugin_node)
    g.connect(Edge(SOURCE_ID, "inline", plugin_node.node_id, "traces"))
    g.set_tap(plugin_node.node_id)
    horizon_id = g.add_horizon_node(horizon_name="top")

    d = g.to_dict()
    rebuilt = Graph.from_dict(
        d,
        plugins={linear_spec.id: linear_spec},
        horizons={"top": object()},
    )

    assert plugin_node.node_id in rebuilt.nodes
    assert rebuilt.nodes[plugin_node.node_id].kind == "plugin"
    assert rebuilt.nodes[plugin_node.node_id].params.scale == 2.0
    assert horizon_id in rebuilt.nodes
    assert rebuilt.nodes[horizon_id].kind == "horizon"
    assert len(rebuilt.edges) == 1
    assert rebuilt.tap_port == (plugin_node.node_id, "out")
    assert len(rebuilt.associations) == 1
    assert rebuilt.associations[0].horizon_node_id == horizon_id
    assert rebuilt.pinned_overlays == {horizon_id}
