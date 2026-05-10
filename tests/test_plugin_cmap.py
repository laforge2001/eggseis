"""Trace-attribute and graph-node decorators carry an optional cmap=."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear():
    from eggseis.plugin import _REGISTRY
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def test_trace_attribute_cmap_round_trips():
    from eggseis.plugin import trace_attribute

    @trace_attribute(name="pretty_attr", version="0.1.0", cmap="batlow")
    def pretty_attr(trace):
        return trace

    spec = _find_spec("pretty_attr")
    assert spec.cmap == "batlow"


def test_trace_attribute_without_cmap_has_none():
    from eggseis.plugin import trace_attribute

    @trace_attribute(name="plain_attr", version="0.1.0")
    def plain_attr(trace):
        return trace

    spec = _find_spec("plain_attr")
    assert spec.cmap is None


def test_trace_attribute_with_unknown_cmap_raises():
    from eggseis.plugin import trace_attribute

    with pytest.raises(ValueError):

        @trace_attribute(name="bogus", version="0.1.0", cmap="not_a_real_cmap")
        def bogus(trace):
            return trace


def test_graph_node_cmap_round_trips():
    from eggseis.plugin import graph_node

    @graph_node(name="multi_in", version="0.1.0", inputs=("a", "b"), cmap="vik")
    def multi_in(a, b):
        return a

    spec = _find_spec("multi_in")
    assert spec.cmap == "vik"


def test_graph_node_without_cmap_has_none():
    from eggseis.plugin import graph_node

    @graph_node(name="plain_node", version="0.1.0", inputs=("x",))
    def plain_node(x):
        return x

    spec = _find_spec("plain_node")
    assert spec.cmap is None


def test_graph_node_with_unknown_cmap_raises():
    from eggseis.plugin import graph_node

    with pytest.raises(ValueError):

        @graph_node(name="bogus_node", version="0.1.0", inputs=("x",), cmap="not_a_real_cmap")
        def bogus_node(x):
            return x


def _find_spec(name: str):
    """Look up a PluginSpec from _REGISTRY by display name."""
    from eggseis.plugin import _REGISTRY
    for spec in _REGISTRY.values():
        if spec.name == name:
            return spec
    raise AssertionError(f"no PluginSpec with name={name!r} in registry")
