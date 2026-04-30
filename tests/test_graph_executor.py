"""GraphExecutor — topo walk + cache + multi-input + cancellation."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict

from eggseis.axes import Axis
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import PluginSpec, clear_registry


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


def _node(spec: PluginSpec, **kw) -> Node:
    return Node(spec=spec, params=spec.param_model(**kw))


# --- 5a: empty graph + Source tap ----------------------------------------


def test_empty_graph_taps_source_inline_emits_raw(qtbot, fake_backend):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()  # tap defaults to (SOURCE_ID, "inline")

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args
    np.testing.assert_array_equal(arr, raw)


def test_source_xline_tap_emits_xline_read(qtbot, fake_backend):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_xline(fake_backend.geometry.xline_min)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    g.set_tap(SOURCE_ID, "xline")

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(g, volume, Axis.XLINE, fake_backend.geometry.xline_min)
    _, arr = blocker.args
    np.testing.assert_array_equal(arr, raw)


def test_timeslice_axis_taps_source_timeslice_port(qtbot, fake_backend):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_timeslice(0)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    g.set_tap(SOURCE_ID, "timeslice")

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(g, volume, Axis.TIMESLICE, 0)
    _, arr = blocker.args
    np.testing.assert_array_equal(arr, raw)


# --- 5b: linear chain ------------------------------------------------------


def test_single_node_chain_emits_function_output(qtbot, fake_backend, linear_spec):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    n = _node(linear_spec, scale=2.0)
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    g.set_tap(n.node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=4000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args
    np.testing.assert_allclose(arr, raw * 2.0, atol=1e-6)


def test_three_node_linear_chain(qtbot, fake_backend, linear_spec):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    c = _node(linear_spec, scale=5.0)
    for n in (a, b, c):
        g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    g.connect(Edge(b.node_id, "out", c.node_id, "traces"))
    g.set_tap(c.node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=4000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args
    np.testing.assert_allclose(arr, raw * 30.0, atol=1e-5)


# --- 5c: branching diamond ------------------------------------------------


def test_diamond_subtract(qtbot, fake_backend, linear_spec, subtract_spec):
    """source.inline -> a (x2), source.inline -> b (x3), then subtract(a,b).
    Expected: raw*2 - raw*3 = -raw."""
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min).astype(np.float32)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
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

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args
    np.testing.assert_allclose(arr, -raw, atol=1e-5)


# --- 5d: cache reuse on warm tap ------------------------------------------


def test_warm_tap_paints_from_cache(qtbot, fake_backend, linear_spec):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    b = _node(linear_spec, scale=3.0)
    g.add_node(a)
    g.add_node(b)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", b.node_id, "traces"))
    g.set_tap(b.node_id)

    # Cold pass — warms cache for both a.out and b.out.
    with qtbot.waitSignal(exe.tapReady, timeout=4000):
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)

    # Warm pass — should resolve fully from cache.
    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args
    raw = volume.read_inline(fake_backend.geometry.inline_min).astype(np.float32)
    np.testing.assert_allclose(arr, raw * 6.0, atol=1e-5)


# --- 5e: cancellation -----------------------------------------------------


def test_request_tap_cancels_in_flight(qtbot, fake_backend, linear_spec):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    g.add_node(a)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.set_tap(a.node_id)

    # Fire two requests back to back; only the second's tapReady should be observed.
    exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    with qtbot.waitSignal(exe.tapReady, timeout=4000):
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min + 1)


# --- 5f: failure ----------------------------------------------------------


def test_unconnected_input_emits_failed(qtbot, fake_backend, subtract_spec):
    from eggseis.graph.executor import GraphExecutor

    volume = SeismicVolume(fake_backend)
    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    s = _node(subtract_spec)
    g.add_node(s)
    # Only wire `a`; `b` is dangling.
    g.connect(Edge(SOURCE_ID, "inline", s.node_id, "a"))
    g.set_tap(s.node_id)

    with qtbot.waitSignal(exe.failed, timeout=2000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, msg = blocker.args
    assert "unconnected" in msg.lower() or "input" in msg.lower()


# --- 5g: determinism poisoning --------------------------------------------


def test_non_deterministic_node_does_not_cache_downstream(qtbot, fake_backend, linear_spec):
    from eggseis.graph.executor import GraphExecutor

    class _P(BaseModel):
        model_config = ConfigDict(extra="forbid")

    nondet = PluginSpec(
        id="tests.nondet_exec",
        name="NonDet",
        func=lambda trace: trace,  # identity but flagged non-deterministic
        param_model=_P,
        params_decl={},
        vectorized=False,
        deterministic=False,
        version="0.1.0",
        source_path=None,
        accepts_context=False,
        inputs=("trace",),
    )

    volume = SeismicVolume(fake_backend)
    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    g = Graph()
    a = _node(linear_spec, scale=2.0)
    nd = Node(spec=nondet, params=_P())
    g.add_node(a)
    g.add_node(nd)
    g.connect(Edge(SOURCE_ID, "inline", a.node_id, "traces"))
    g.connect(Edge(a.node_id, "out", nd.node_id, "trace"))
    g.set_tap(nd.node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=4000):
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)

    # Linear node 'a' is deterministic and should be cached.
    a_hash = g.port_hash(a.node_id, "out", volume.version, "inline")
    a_cached = next(
        (v for k, v in orch.cache._items.items() if k.chain_hash == a_hash), None
    )
    assert a_cached is not None

    # Non-deterministic node should NOT be in cache.
    nd_hash = g.port_hash(nd.node_id, "out", volume.version, "inline")
    nd_cached = next(
        (v for k, v in orch.cache._items.items() if k.chain_hash == nd_hash), None
    )
    assert nd_cached is None
