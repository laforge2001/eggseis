"""Pipeline data model tests — pure Python, no Qt."""
from __future__ import annotations


def test_node_assigns_uuid_node_id(linear_spec):
    from eggseis.pipeline.model import Node

    n1 = Node(spec=linear_spec, params=linear_spec.param_model())
    n2 = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n1.node_id != n2.node_id
    assert len(n1.node_id) == 32  # uuid4().hex


def test_node_default_enabled(linear_spec):
    from eggseis.pipeline.model import Node

    assert Node(spec=linear_spec, params=linear_spec.param_model()).enabled is True
