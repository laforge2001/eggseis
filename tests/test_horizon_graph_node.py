"""Horizon node Graph integration."""

from __future__ import annotations

import pytest

from eggseis.graph.model import SOURCE_ID, Graph, Node


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
