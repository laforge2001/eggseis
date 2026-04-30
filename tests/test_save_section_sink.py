"""Sink plugins: section-level side-effect nodes that pass input through."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.axes import Axis
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.graph.executor import GraphExecutor
from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import clear_registry


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


def _node(spec, **kw) -> Node:
    return Node(spec=spec, params=spec.param_model(**kw))


def test_save_section_npy_writes_file_and_passes_through(qtbot, fake_backend, tmp_path):
    from eggseis.builtins.save_section_npy import save_section_npy

    out_path = tmp_path / "section.npy"
    spec = save_section_npy._eggseis_spec
    assert spec.kind == "sink"
    assert spec.inputs == ("trace",)

    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    g = Graph()
    n = _node(spec, path=str(out_path))
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "trace"))
    g.set_tap(n.node_id)

    orch = JobOrchestrator()
    exe = GraphExecutor(orch)
    with qtbot.waitSignal(exe.tapReady, timeout=4000) as blocker:
        exe.request_tap(g, volume, Axis.INLINE, fake_backend.geometry.inline_min)
    _, arr = blocker.args

    # Side effect: file exists with the input contents.
    assert out_path.exists()
    saved = np.load(out_path)
    np.testing.assert_array_equal(saved, raw)

    # Passthrough: tap output equals input.
    np.testing.assert_array_equal(arr, raw)
