"""Tests for the M6 graph data model: topology, port_hash, undo/redo, serialise."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from eggseis.graph.model import (
    SOURCE_ID,
    SOURCE_PORTS,
    CycleError,
    Edge,
    Graph,
    Node,
    OrphanPluginError,
)
from eggseis.plugin import PluginSpec

VV = ("mdio", "/x", 1, 1)


def _node(spec: PluginSpec, **kw) -> Node:
    return Node(spec=spec, params=spec.param_model(**kw))


# --- topology --------------------------------------------------------------


def test_empty_graph_default_tap_is_source_inline():
    g = Graph()
    assert g.tap_port == (SOURCE_ID, "inline")
    assert g.nodes == {}
    assert g.edges == []


def test_add_node_and_connect_from_source(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    assert n.node_id in g.nodes
    assert len(g.edges) == 1


def test_cannot_add_node_with_source_id(linear_spec):
    g = Graph()
    with pytest.raises(ValueError, match="reserved"):
        g.add_node(Node(spec=linear_spec, params=linear_spec.param_model(), node_id=SOURCE_ID))


def test_cannot_remove_source(linear_spec):
    g = Graph()
    with pytest.raises(ValueError, match="Source"):
        g.remove_node(SOURCE_ID)


def test_remove_node_drops_incident_edges(linear_spec):
    g = Graph()
    a = _node(linear_spec)
    b = _node(linear_spec)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    g.remove_node(a.node_id)
    assert a.node_id not in g.nodes
    assert g.edges == []


def test_connect_replaces_existing_inbound_edge(linear_spec):
    g = Graph()
    a = _node(linear_spec)
    b = _node(linear_spec)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", b.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    # Second connect replaces source->b with a->b on the same dst port.
    assert len(g.edges) == 1
    incoming = g.incoming_edges(b.node_id)
    assert incoming["traces"].src_node_id == a.node_id


def test_connect_invalid_source_port_raises(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    with pytest.raises(ValueError, match="Source has no output port"):
        g.connect(Edge(SOURCE_ID, "garbage", n.node_id, "traces"))


def test_connect_invalid_dst_port_raises(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    with pytest.raises(ValueError, match="no input port"):
        g.connect(Edge(SOURCE_ID, "inline", n.node_id, "garbage"))


def test_cycle_rejected_on_connect(linear_spec):
    g = Graph()
    a = _node(linear_spec)
    b = _node(linear_spec)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    with pytest.raises(CycleError, match="cycle"):
        g.connect(Edge(b.node_id, "out", a.node_id, "traces"))
    # State unchanged after rejected connect.
    assert len(g.edges) == 2


def test_disable_multi_input_raises(subtract_spec):
    g = Graph()
    n = _node(subtract_spec)
    g.add_node(n)
    with pytest.raises(ValueError, match="multi-input"):
        g.set_enabled(n.node_id, False)


# --- port_hash --------------------------------------------------------------


def test_port_hash_source_axis_distinct(linear_spec):
    g = Graph()
    h_inline = g.port_hash(SOURCE_ID, "inline", VV, "inline")
    h_xline = g.port_hash(SOURCE_ID, "xline", VV, "xline")
    assert h_inline != h_xline


def test_port_hash_stable_across_param_orderings(linear_spec):
    g1 = Graph()
    n1 = _node(linear_spec, scale=2.0)
    g1.add_node(n1)
    g1.connect(Edge(SOURCE_ID, "inline", n1.node_id, "traces"))

    g2 = Graph()
    n2 = _node(linear_spec, scale=2.0)
    g2.add_node(n2)
    g2.connect(Edge(SOURCE_ID, "inline", n2.node_id, "traces"))

    assert g1.port_hash(n1.node_id, "out", VV, "inline") == \
           g2.port_hash(n2.node_id, "out", VV, "inline")


def test_port_hash_changes_when_upstream_changes(linear_spec):
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    h_before = g.port_hash(b.node_id, "out", VV, "inline")
    # Change upstream params.
    g.set_params(a.node_id, linear_spec.param_model(scale=5.0))
    h_after = g.port_hash(b.node_id, "out", VV, "inline")
    assert h_before != h_after


def test_port_hash_invariant_under_input_edge_iteration_order(subtract_spec, linear_spec):
    # Two inputs into subtract; hashing must sort inputs so iteration
    # order doesn't perturb the digest.
    g1 = Graph()
    a1 = _node(linear_spec, scale=2.0)
    b1 = _node(linear_spec, scale=3.0)
    s1 = _node(subtract_spec)
    g1.add_node(a1)
    g1.add_node(b1)
    g1.add_node(s1)
    g1.connect(Edge(SOURCE_ID, "inline", a1.node_id, "traces"))
    g1.connect(Edge(SOURCE_ID, "inline", b1.node_id, "traces"))
    g1.connect(Edge(a1.node_id, "out", s1.node_id, "a"))
    g1.connect(Edge(b1.node_id, "out", s1.node_id, "b"))

    g2 = Graph()
    a2 = _node(linear_spec, scale=2.0)
    b2 = _node(linear_spec, scale=3.0)
    s2 = _node(subtract_spec)
    g2.add_node(a2)
    g2.add_node(b2)
    g2.add_node(s2)
    g2.connect(Edge(SOURCE_ID, "inline", a2.node_id, "traces"))
    g2.connect(Edge(SOURCE_ID, "inline", b2.node_id, "traces"))
    # Connect b first this time:
    g2.connect(Edge(b2.node_id, "out", s2.node_id, "b"))
    g2.connect(Edge(a2.node_id, "out", s2.node_id, "a"))

    assert g1.port_hash(s1.node_id, "out", VV, "inline") == \
           g2.port_hash(s2.node_id, "out", VV, "inline")


def test_port_hash_disabled_single_input_passes_parent_through(linear_spec):
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))

    h_b_enabled = g.port_hash(b.node_id, "out", VV, "inline")
    g.set_enabled(b.node_id, False)
    h_b_disabled = g.port_hash(b.node_id, "out", VV, "inline")
    h_a = g.port_hash(a.node_id, "out", VV, "inline")

    assert h_b_disabled == h_a
    assert h_b_enabled != h_a


def test_port_hash_unconnected_input_raises(subtract_spec):
    g = Graph()
    s = _node(subtract_spec)
    g.add_node(s)
    with pytest.raises(ValueError, match="unconnected"):
        g.port_hash(s.node_id, "out", VV, "inline")


def test_deterministic_through_propagates(linear_spec):
    # Construct a non-deterministic spec by hand to avoid clear_registry
    # collision with linear_spec fixture.

    class _P(BaseModel):
        model_config = ConfigDict(extra="forbid")

    nondet = PluginSpec(
        id="tests.nondet",
        name="NonDet",
        func=lambda trace: trace,
        param_model=_P,
        params_decl={},
        vectorized=False,
        deterministic=False,
        version="0.1.0",
        source_path=None,
        accepts_context=False,
        inputs=("trace",),
    )

    g = Graph()
    a = _node(linear_spec, scale=2.0)
    nd = Node(spec=nondet, params=_P())
    b = _node(linear_spec, scale=3.0)
    g.add_node(a)
    g.add_node(nd)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", nd.node_id, "trace"))
    g.connect(Edge(nd.node_id, "out", b.node_id, "traces"))

    assert g.deterministic_through(a.node_id, "out") is True
    assert g.deterministic_through(nd.node_id, "out") is False
    assert g.deterministic_through(b.node_id, "out") is False


# --- topo / cone -----------------------------------------------------------


def test_upstream_cone_diamond(linear_spec, subtract_spec):
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    s = _node(subtract_spec)
    g.add_node(a)
    g.add_node(b)
    g.add_node(s)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(SOURCE_ID, "inline", b.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", s.node_id, "a"))
    g.connect(Edge(b.node_id, "out", s.node_id, "b"))

    cone = g.upstream_cone(s.node_id, "out")
    assert cone[0] == SOURCE_ID
    assert cone[-1] == s.node_id
    assert set(cone) == {SOURCE_ID, a.node_id, b.node_id, s.node_id}


# --- undo / redo -----------------------------------------------------------


def test_undo_add_node(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    assert n.node_id in g.nodes
    g.undo()
    assert n.node_id not in g.nodes


def test_undo_remove_node_restores_edges(linear_spec):
    g = Graph()
    a = _node(linear_spec)
    b = _node(linear_spec)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    g.remove_node(a.node_id)
    assert a.node_id not in g.nodes
    g.undo()
    assert a.node_id in g.nodes
    assert len(g.edges) == 2


def test_undo_set_params_restores(linear_spec):
    g = Graph()
    n = _node(linear_spec, scale=2.0)
    g.add_node(n)
    g.set_params(n.node_id, linear_spec.param_model(scale=5.0))
    assert n.params.scale == 5.0
    g.undo()
    assert g.nodes[n.node_id].params.scale == 2.0


def test_undo_set_tap_restores(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    prev = g.tap_port
    g.set_tap(n.node_id)
    g.undo()
    assert g.tap_port == prev


def test_redo_after_undo(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    g.undo()
    assert n.node_id not in g.nodes
    g.redo()
    assert n.node_id in g.nodes


# --- serialisation ---------------------------------------------------------


def test_to_dict_from_dict_round_trip(linear_spec, subtract_spec):
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    s = _node(subtract_spec)
    g.add_node(a)
    g.add_node(b)
    g.add_node(s)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(SOURCE_ID, "inline", b.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", s.node_id, "a"))
    g.connect(Edge(b.node_id, "out", s.node_id, "b"))
    g.set_tap(s.node_id, "out")

    d = g.to_dict()
    registry = {linear_spec.id: linear_spec, subtract_spec.id: subtract_spec}
    g2 = Graph.from_dict(d, registry)

    assert set(g2.nodes.keys()) == set(g.nodes.keys())
    assert g2.tap_port == g.tap_port
    assert len(g2.edges) == len(g.edges)
    # Hash should match exactly.
    assert g.port_hash(s.node_id, "out", VV, "inline") == \
           g2.port_hash(s.node_id, "out", VV, "inline")


def test_from_dict_unknown_plugin_raises(linear_spec):
    g = Graph()
    n = _node(linear_spec)
    g.add_node(n)
    d = g.to_dict()
    with pytest.raises(OrphanPluginError):
        Graph.from_dict(d, registry={})


# --- module exports ----------------------------------------------------


def test_source_ports_constant_unchanged():
    assert SOURCE_PORTS == ("inline", "xline", "timeslice")


def test_invalid_source_tap_port_raises():
    g = Graph()
    with pytest.raises(ValueError, match="Source has no output port"):
        g.set_tap(SOURCE_ID, "garbage")


def test_unconnected_source_inline_hash_is_deterministic():
    g = Graph()
    h1 = g.port_hash(SOURCE_ID, "inline", VV, "inline")
    h2 = g.port_hash(SOURCE_ID, "inline", VV, "inline")
    assert h1 == h2
    # Different volume_version should produce different hash.
    h3 = g.port_hash(SOURCE_ID, "inline", ("mdio", "/y", 1, 1), "inline")
    assert h1 != h3
