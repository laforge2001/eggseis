"""Pipeline data model tests — pure Python, no Qt."""
from __future__ import annotations

import pytest


def test_node_assigns_uuid_node_id(linear_spec):
    from eggseis.pipeline.model import Node

    n1 = Node(spec=linear_spec, params=linear_spec.param_model())
    n2 = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n1.node_id != n2.node_id
    assert len(n1.node_id) == 32  # uuid4().hex


def test_node_default_enabled(linear_spec):
    from eggseis.pipeline.model import Node

    assert Node(spec=linear_spec, params=linear_spec.param_model()).enabled is True


def test_append_adds_node_at_end(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    assert p.nodes == [n]


def test_remove_drops_node_by_id(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.remove(a.node_id)
    assert p.nodes == [b]


def test_remove_unknown_raises(linear_spec):
    from eggseis.pipeline.model import Pipeline

    p = Pipeline()
    with pytest.raises(KeyError):
        p.remove("does-not-exist")


def test_move_reorders(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.move(c.node_id, 0)
    assert [n.node_id for n in p.nodes] == [c.node_id, a.node_id, b.node_id]


def test_set_enabled_flips_flag(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    p.set_enabled(n.node_id, False)
    assert p.nodes[0].enabled is False
    p.set_enabled(n.node_id, True)
    assert p.nodes[0].enabled is True


def test_set_params_replaces_pydantic_model(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model(scale=1.0))
    p.append(n)
    new_params = linear_spec.param_model(scale=4.0)
    p.set_params(n.node_id, new_params)
    assert p.nodes[0].params.scale == 4.0
