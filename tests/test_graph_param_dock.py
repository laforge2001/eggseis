"""GraphParamDock — selection-driven per-node param editor."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.graph.model import Graph, Node
from eggseis.plugin import Param, clear_registry, trace_attribute


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def scaled_spec():
    @trace_attribute(name="Scaled", version="0.1.0", vectorized=True)
    def scaled(traces: np.ndarray, scale: float = Param(default=1.0)) -> np.ndarray:
        return traces * scale
    return scaled._eggseis_spec


def test_show_node_switches_widget(qtbot, scaled_spec):
    from eggseis.graph.param_dock import GraphParamDock

    g = Graph()
    n1 = Node(spec=scaled_spec, params=scaled_spec.param_model(scale=2.0))
    n2 = Node(spec=scaled_spec, params=scaled_spec.param_model(scale=5.0))
    g.add_node(n1)
    g.add_node(n2)

    dock = GraphParamDock()
    qtbot.addWidget(dock)
    dock.bind(g)

    dock.show_node(n1.node_id)
    assert dock.current_node_id() == n1.node_id

    dock.show_node(n2.node_id)
    assert dock.current_node_id() == n2.node_id


def test_show_none_displays_empty(qtbot, scaled_spec):
    from eggseis.graph.param_dock import GraphParamDock

    g = Graph()
    n = Node(spec=scaled_spec, params=scaled_spec.param_model())
    g.add_node(n)

    dock = GraphParamDock()
    qtbot.addWidget(dock)
    dock.bind(g)
    dock.show_node(n.node_id)
    dock.show_node(None)
    assert dock.current_node_id() is None


def test_param_change_emits_params_changed_signal(qtbot, scaled_spec):
    from eggseis.graph.param_dock import GraphParamDock

    g = Graph()
    n = Node(spec=scaled_spec, params=scaled_spec.param_model(scale=1.0))
    g.add_node(n)

    dock = GraphParamDock()
    qtbot.addWidget(dock)
    dock.bind(g)
    dock.show_node(n.node_id)

    received: list = []
    dock.paramsChanged.connect(lambda nid, params: received.append((nid, params)))

    # Drive a programmatic param change via the inner widget.
    inner = dock.inner_dock_for(n.node_id)
    new_params = scaled_spec.param_model(scale=4.0)
    inner.paramsChanged.emit(new_params)

    assert len(received) == 1
    assert received[0][0] == n.node_id
    assert received[0][1].scale == 4.0


def test_bind_to_new_graph_drops_old_widgets(qtbot, scaled_spec):
    from eggseis.graph.param_dock import GraphParamDock

    g1 = Graph()
    n1 = Node(spec=scaled_spec, params=scaled_spec.param_model())
    g1.add_node(n1)

    g2 = Graph()
    n2 = Node(spec=scaled_spec, params=scaled_spec.param_model())
    g2.add_node(n2)

    dock = GraphParamDock()
    qtbot.addWidget(dock)
    dock.bind(g1)
    dock.show_node(n1.node_id)
    assert dock.inner_dock_for(n1.node_id) is not None

    dock.bind(g2)
    assert dock.inner_dock_for(n1.node_id) is None
    assert dock.inner_dock_for(n2.node_id) is not None
    assert dock.current_node_id() is None


def test_node_removed_from_graph_drops_inner_dock(qtbot, scaled_spec):
    from eggseis.graph.param_dock import GraphParamDock

    g = Graph()
    n = Node(spec=scaled_spec, params=scaled_spec.param_model())
    g.add_node(n)

    dock = GraphParamDock()
    qtbot.addWidget(dock)
    dock.bind(g)
    dock.show_node(n.node_id)
    assert dock.inner_dock_for(n.node_id) is not None

    g.remove_node(n.node_id)
    dock.refresh()
    assert dock.inner_dock_for(n.node_id) is None
    assert dock.current_node_id() is None
