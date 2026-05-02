"""Horizon node Graph integration."""

from __future__ import annotations

from eggseis.graph.model import Node


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
