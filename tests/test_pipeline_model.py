"""Pipeline data model tests — pure Python, no Qt."""
from __future__ import annotations

import pytest

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


def test_node_assigns_uuid_node_id(linear_spec):
    n1 = Node(spec=linear_spec, params=linear_spec.param_model())
    n2 = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n1.node_id != n2.node_id
    assert len(n1.node_id) == 32  # uuid4().hex


def test_node_default_enabled(linear_spec):
    assert Node(spec=linear_spec, params=linear_spec.param_model()).enabled is True


def test_append_adds_node_at_end(linear_spec):
    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    assert p.nodes == [n]


def test_remove_drops_node_by_id(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.remove(a.node_id)
    assert p.nodes == [b]


def test_remove_unknown_raises(linear_spec):
    p = Pipeline()
    with pytest.raises(KeyError):
        p.remove("does-not-exist")


def test_move_reorders(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.move(c.node_id, 0)
    assert [n.node_id for n in p.nodes] == [c.node_id, a.node_id, b.node_id]


def test_set_enabled_flips_flag(linear_spec):
    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    p.set_enabled(n.node_id, False)
    assert p.nodes[0].enabled is False
    p.set_enabled(n.node_id, True)
    assert p.nodes[0].enabled is True


def test_set_params_replaces_pydantic_model(linear_spec):
    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model(scale=1.0))
    p.append(n)
    new_params = linear_spec.param_model(scale=4.0)
    p.set_params(n.node_id, new_params)
    assert p.nodes[0].params.scale == 4.0


def test_set_tap_to_node_id_succeeds_when_enabled(linear_spec):
    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    p.set_tap(n.node_id)
    assert p.tap_node_id == n.node_id


def test_set_tap_to_disabled_node_shifts_upstream(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    assert p.tap_node_id == a.node_id


def test_set_tap_falls_through_to_source_when_no_enabled_ancestor(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    assert p.tap_node_id == SOURCE_ID


def test_disable_tapped_node_auto_shifts_tap(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    p.set_enabled(b.node_id, False)
    assert p.tap_node_id == a.node_id


def test_set_tap_to_source_always_allowed(linear_spec):
    p = Pipeline()
    p.set_tap(SOURCE_ID)
    assert p.tap_node_id == SOURCE_ID


def test_nodes_up_to_tap_empty_when_tap_is_source(linear_spec):
    p = Pipeline()
    p.append(Node(spec=linear_spec, params=linear_spec.param_model()))
    assert p.nodes_up_to_tap() == []


def test_nodes_up_to_tap_returns_inclusive_slice(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.set_tap(b.node_id)
    assert [n.node_id for n in p.nodes_up_to_tap()] == [a.node_id, b.node_id]


def test_nodes_up_to_tap_filters_disabled(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.set_tap(c.node_id)
    assert [n.node_id for n in p.nodes_up_to_tap()] == [a.node_id, c.node_id]


def test_remove_tapped_node_resets_tap_to_source(linear_spec):
    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    p.remove(b.node_id)
    assert p.tap_node_id == SOURCE_ID
