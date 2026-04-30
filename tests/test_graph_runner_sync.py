"""Synchronous graph runner — no Qt, no orchestrator. Powers volume export."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import clear_registry


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


def _node(spec, **kw) -> Node:
    return Node(spec=spec, params=spec.param_model(**kw))


def test_run_sync_empty_graph_returns_raw(fake_backend, linear_spec):
    from eggseis.graph.runner import run_graph_on_section

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    g = Graph()  # tap defaults to (SOURCE_ID, "inline")
    out = run_graph_on_section(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    np.testing.assert_array_equal(out, raw)


def test_run_sync_single_node_chain(fake_backend, linear_spec):
    from eggseis.graph.runner import run_graph_on_section

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    g = Graph()
    n = _node(linear_spec, scale=2.0)
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    g.set_tap(n.node_id)

    out = run_graph_on_section(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    np.testing.assert_allclose(out, raw * 2.0, atol=1e-6)


def test_run_sync_multi_input_subtract(fake_backend, linear_spec, subtract_spec):
    from eggseis.graph.runner import run_graph_on_section

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min).astype(np.float32)

    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    s = _node(subtract_spec)
    for n in (a, b, s):
        g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(SOURCE_ID, "inline", b.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", s.node_id, "a"))
    g.connect(Edge(b.node_id, "out", s.node_id, "b"))
    g.set_tap(s.node_id)

    out = run_graph_on_section(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    np.testing.assert_allclose(out, -raw, atol=1e-5)
