"""Headless tests for the qtpynodeeditor-backed GraphCanvas widget."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import clear_registry, graph_node, trace_attribute

qtpynodeeditor = pytest.importorskip("qtpynodeeditor")


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def canvas(qtbot):
    from eggseis.graph.canvas import GraphCanvas

    widget = GraphCanvas()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def linear_attr():
    @trace_attribute(name="LinearScale", version="0.1.0", vectorized=True)
    def linear(traces: np.ndarray) -> np.ndarray:
        return traces
    return linear._eggseis_spec


@pytest.fixture
def subtract_attr():
    @graph_node(name="Subtract", version="0.1.0", inputs=("a", "b"))
    def sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b
    return sub._eggseis_spec


def test_bind_empty_graph_renders_only_source(canvas):
    g = Graph()
    canvas.bind(g)
    # Source node should be present in the scene.
    assert canvas.has_source_node()


def test_add_plugin_adds_node_to_graph_and_scene(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    assert node_id in g.nodes
    assert canvas.scene_node_count() == 2  # Source + the new node


def test_add_multi_input_plugin_renders_multiple_input_ports(canvas, subtract_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(subtract_attr)
    assert g.nodes[node_id].spec.inputs == ("a", "b")
    assert canvas.scene_input_port_count(node_id) == 2


def test_remove_node_drops_from_graph_and_scene(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    canvas.remove_node(node_id)
    assert node_id not in g.nodes
    assert canvas.scene_node_count() == 1  # Source only


def test_connect_edge_via_canvas_appends_to_graph(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    edge = Edge(SOURCE_ID, "inline", node_id, "traces")
    canvas.connect_edge(edge)
    assert edge in g.edges


def test_cycle_attempt_blocked_pre_check(canvas, linear_attr):
    """Wiring a back-edge must be rejected before scene-level connect lands."""
    g = Graph()
    canvas.bind(g)
    a = canvas.add_plugin(linear_attr)
    b = canvas.add_plugin(linear_attr)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", a, "traces"))
    canvas.connect_edge(Edge(a, "out", b, "traces"))
    from eggseis.graph.model import CycleError
    with pytest.raises(CycleError):
        canvas.connect_edge(Edge(b, "out", a, "traces"))
    # State unchanged.
    incoming = g.incoming_edges(a.node_id if isinstance(a, Node) else a)
    assert "traces" in incoming
    assert incoming["traces"].src_node_id == SOURCE_ID


def test_set_tap_emits_signal(canvas, linear_attr, qtbot):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", node_id, "traces"))

    with qtbot.waitSignal(canvas.tapPortChanged, timeout=500) as blocker:
        canvas.set_tap(node_id, "out")
    assert blocker.args == [node_id, "out"]
    assert g.tap_port == (node_id, "out")


def test_disconnect_via_canvas_drops_edge(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    edge = Edge(SOURCE_ID, "inline", node_id, "traces")
    canvas.connect_edge(edge)
    canvas.disconnect_edge(edge)
    assert edge not in g.edges


def test_user_drag_wire_syncs_to_graph(canvas, linear_attr):
    """Simulate user-drag: scene.create_connection bypasses connect_edge."""
    from qtpynodeeditor import PortType

    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    src_node = canvas._source_scene_node
    dst_node = canvas.scene_node_for(node_id)

    canvas._scene.create_connection(
        src_node[PortType.output][0],   # inline
        dst_node[PortType.input][0],    # traces
    )
    assert any(
        e.src_node_id == SOURCE_ID and e.src_port == "inline"
        and e.dst_node_id == node_id and e.dst_port == "traces"
        for e in g.edges
    )


def test_user_drag_cycle_attempt_rejected(canvas, linear_attr):
    """User-drag of a back-edge must not appear in the graph.

    Lib's own cycle detection is the first defence (it raises before our
    signal handler runs), but our handler also pre-checks via
    `Graph.has_cycle_if_added` for any case where the lib path may change.
    """
    from qtpynodeeditor import PortType
    from qtpynodeeditor.exceptions import ConnectionCycleFailure

    g = Graph()
    canvas.bind(g)
    a = canvas.add_plugin(linear_attr)
    b = canvas.add_plugin(linear_attr)
    canvas.connect_edge(Edge(a, "out", b, "traces"))  # a -> b only

    a_node = canvas.scene_node_for(a)
    b_node = canvas.scene_node_for(b)
    # User drags b.out -> a.traces (would form a -> b -> a cycle).
    try:
        canvas._scene.create_connection(
            b_node[PortType.output][0],
            a_node[PortType.input][0],
        )
    except ConnectionCycleFailure:
        # Lib caught it directly. That's the primary defence.
        pass
    # Graph state unchanged regardless of which layer caught the cycle.
    assert len(g.edges) == 1
    assert not any(e.src_node_id == b and e.dst_node_id == a for e in g.edges)


def test_user_drag_disconnect_syncs_to_graph(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    edge = Edge(SOURCE_ID, "inline", node_id, "traces")
    canvas.connect_edge(edge)
    # User deletes the wire on the canvas.
    dst_node = canvas.scene_node_for(node_id)
    from qtpynodeeditor import PortType
    conn = next(iter(dst_node[PortType.input][0].connections))
    canvas._scene.delete_connection(conn)
    assert edge not in g.edges


def test_selection_changed_emits_graph_node_id(canvas, linear_attr, qtbot):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    scene_node = canvas.scene_node_for(node_id)

    received = []
    canvas.selectionChanged.connect(lambda nid: received.append(nid))

    # Programmatically select the scene node by setting its graphics item
    # selection state. qtpynodeeditor exposes the underlying QGraphicsItem.
    scene_node.graphics_object.setSelected(True)
    # selectionChanged fires synchronously from QGraphicsScene.
    assert any(r == node_id for r in received)


def test_canvas_does_not_tap_on_double_click(canvas, linear_attr, qtbot):
    """Double-click is consumed by MainWindow for params popup, not by canvas."""
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", node_id, "traces"))
    initial_tap = g.tap_port
    canvas._scene.node_double_clicked.emit(canvas.scene_node_for(node_id))
    # Tap port unchanged — canvas no longer hooks node_double_clicked.
    assert g.tap_port == initial_tap


def test_set_node_enabled_toggles_graph_and_opacity(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", node_id, "traces"))

    canvas.set_node_enabled(node_id, False)
    assert g.nodes[node_id].enabled is False
    assert canvas.scene_node_for(node_id).graphics_object.opacity() < 0.5

    canvas.set_node_enabled(node_id, True)
    assert g.nodes[node_id].enabled is True
    assert canvas.scene_node_for(node_id).graphics_object.opacity() == 1.0


def test_set_node_enabled_rejects_multi_input(canvas, subtract_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(subtract_attr)
    canvas.connect_edge(Edge(SOURCE_ID, "inline", node_id, "a"))
    canvas.connect_edge(Edge(SOURCE_ID, "inline", node_id, "b"))
    with pytest.raises(ValueError, match="multi-input"):
        canvas.set_node_enabled(node_id, False)


def test_position_round_trips_through_bind(canvas, linear_attr):
    g = Graph()
    canvas.bind(g)
    node_id = canvas.add_plugin(linear_attr, pos=(150.0, -75.0))
    g.nodes[node_id].pos = (150.0, -75.0)
    # Re-bind from scratch should preserve position.
    canvas.bind(g)
    scene_node = canvas.scene_node_for(node_id)
    pos = scene_node.position
    assert abs(pos.x() - 150.0) < 1.0
    assert abs(pos.y() - -75.0) < 1.0
