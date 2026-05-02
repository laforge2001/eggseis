"""Horizon node Graph integration."""

from __future__ import annotations

import pytest

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
