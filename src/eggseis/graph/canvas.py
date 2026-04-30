"""GraphCanvas — qtpynodeeditor-backed visual node-graph widget.

Owns a `FlowScene` + `FlowView` and translates user interactions into
mutations on the bound `Graph` model. The lib's data-propagation is
suppressed: our nodes' `set_in_data` is a no-op and we never emit
`data_updated`. All compute lives in `GraphExecutor`.

Cycles are blocked by pre-validating every wire against
`Graph.has_cycle_if_added` before calling `scene.create_connection`,
since the lib's `ConnectionCycleFailure` leaves dangling state.
"""

from __future__ import annotations

import qtpynodeeditor as qne
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qtpynodeeditor import (
    DataModelRegistry,
    FlowScene,
    NodeData,
    NodeDataModel,
    NodeDataType,
    PortType,
)

from eggseis.graph.model import SOURCE_ID, SOURCE_PORTS, CycleError, Edge, Graph, Node
from eggseis.plugin import PluginSpec

try:
    from PySide6.QtCore import Signal
except ImportError:  # pragma: no cover
    from qtpy.QtCore import Signal  # type: ignore


_SECTION_TYPE = NodeDataType("section", "Section")


class _SectionData(NodeData):
    """Sentinel — actual ndarray lives in GraphExecutor's cache."""

    data_type = _SECTION_TYPE


def _section_dict(input_names: tuple[str, ...], output_names: tuple[str, ...]) -> dict:
    return {
        "input": {i: _SECTION_TYPE for i in range(len(input_names))},
        "output": {i: _SECTION_TYPE for i in range(len(output_names))},
    }


class _SourceModel(NodeDataModel):
    """Implicit Source node with three output ports (inline/xline/timeslice)."""

    name = "Source"
    caption = "Source"
    caption_visible = True
    num_ports = {PortType.input: 0, PortType.output: 3}
    data_type = _section_dict((), SOURCE_PORTS)
    port_caption_visible = True
    port_caption = {
        "input": {},
        "output": dict(enumerate(SOURCE_PORTS)),
    }
    eggseis_node_id = SOURCE_ID

    def out_data(self, port: int) -> NodeData | None:
        return _SectionData()

    def set_in_data(self, data: NodeData, port) -> None:  # type: ignore[override]
        # No-op: Source has no inputs.
        return


def _make_plugin_model_class(spec: PluginSpec) -> type[NodeDataModel]:
    """Build a NodeDataModel subclass for the given plugin spec.

    `_section_dict` must be passed as a class-level attr — the lib reads it
    at class-def time. We never emit `data_updated`; compute is owned by
    GraphExecutor.
    """

    inputs = spec.inputs
    safe_class = spec.id.replace(".", "_").replace("-", "_")

    class _Model(NodeDataModel):
        name = safe_class
        caption = spec.name
        caption_visible = True
        num_ports = {PortType.input: len(inputs), PortType.output: 1}
        data_type = _section_dict(inputs, ("out",))
        port_caption_visible = True
        port_caption = {
            "input": dict(enumerate(inputs)),
            "output": {0: "out"},
        }
        plugin_id = spec.id
        plugin_version = spec.version

        def out_data(self, port: int) -> NodeData | None:  # type: ignore[override]
            return _SectionData()

        def set_in_data(self, data: NodeData, port) -> None:  # type: ignore[override]
            # No-op: lib's data-propagation is decorative for us.
            return

    _Model.__name__ = safe_class
    return _Model


class GraphCanvas(QWidget):
    """Visual canvas widget. Sync rendering with a bound Graph model."""

    nodeAdded = Signal(str)               # node_id
    nodeRemoved = Signal(str)             # node_id
    edgeChanged = Signal()                # any structural connect/disconnect
    tapPortChanged = Signal(str, str)     # node_id, port
    selectionChanged = Signal(str)        # node_id selected (or "")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._graph: Graph | None = None
        self._registry = DataModelRegistry()
        self._scene = FlowScene(registry=self._registry)
        self._view = qne.FlowView(self._scene)
        self._scene_nodes: dict[str, qne.Node] = {}  # graph node_id -> scene node
        self._source_scene_node: qne.Node | None = None
        self._registered_specs: dict[str, type[NodeDataModel]] = {}
        self._spec_by_class: dict[str, PluginSpec] = {}
        self._suppress_signal_sync = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._registry.register_model(_SourceModel, category="eggseis")
        self._scene.connection_created.connect(self._on_lib_connection_created)
        self._scene.connection_deleted.connect(self._on_lib_connection_deleted)
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._scene.node_created.connect(self._on_lib_node_created)
        # Note: double-click is intentionally NOT consumed here. MainWindow
        # routes node_double_clicked to a parameters popup; tap-on-output
        # lives on the right-click context menu instead.

    # --- public API ----------------------------------------------------

    def bind(self, graph: Graph) -> None:
        """Wipe the scene and render `graph` from scratch."""
        self._graph = graph
        self._rerender()

    def register_specs(self, specs) -> None:
        """Pre-register plugin specs so they show in the lib's right-click menu.

        qtpynodeeditor's FlowView builds its 'create node' context menu from
        DataModelRegistry.categories(); only registered models appear there.
        Call this once at MainWindow setup to surface all discovered plugins.
        """
        for spec in specs:
            self._ensure_spec_registered(spec)

    def _ensure_spec_registered(self, spec: PluginSpec) -> type[NodeDataModel]:
        model_cls = self._registered_specs.get(spec.id)
        if model_cls is None:
            model_cls = _make_plugin_model_class(spec)
            self._registry.register_model(model_cls, category="eggseis")
            self._registered_specs[spec.id] = model_cls
            self._spec_by_class[model_cls.__name__] = spec
        return model_cls

    def add_plugin(self, spec: PluginSpec, pos: tuple[float, float] | None = None) -> str:
        """Add a node for `spec` to the bound graph and scene; return node_id."""
        if self._graph is None:
            raise RuntimeError("canvas not bound to a graph")
        node = Node(spec=spec, params=spec.param_model())
        if pos is not None:
            node.pos = pos
        else:
            node.pos = self._next_default_position()
        self._graph.add_node(node)
        self._spawn_scene_node(node)
        self.nodeAdded.emit(node.node_id)
        return node.node_id

    def _next_default_position(self) -> tuple[float, float]:
        """Pick a position inside the current viewport, cascading rightward.

        Per-node ports are input-left / output-right (lib default; vertical
        port orientation is not supported by qtpynodeeditor). Cascade matches
        port flow: new nodes appear to the right of existing ones with a
        small vertical nudge per column.
        """
        try:
            visible = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
            cx = visible.left() + visible.width() * 0.2
            cy = visible.top() + visible.height() * 0.4
        except Exception:
            cx, cy = 200.0, 0.0
        n = len(self._graph.nodes) if self._graph is not None else 0
        return (cx + 200.0 * n, cy + 40.0 * (n % 3))

    def set_node_enabled(self, node_id: str, on: bool) -> None:
        """Enable/disable a node and re-render to reflect the visual state."""
        if self._graph is None or node_id == SOURCE_ID:
            return
        self._graph.set_enabled(node_id, on)
        scene_node = self._scene_nodes.get(node_id)
        if scene_node is not None:
            # Visual cue — dim the node's opacity so disabled state is obvious.
            scene_node.graphics_object.setOpacity(1.0 if on else 0.4)
        self.edgeChanged.emit()

    def remove_node(self, node_id: str) -> None:
        if self._graph is None:
            return
        self._graph.remove_node(node_id)
        scene_node = self._scene_nodes.pop(node_id, None)
        if scene_node is not None:
            self._scene.remove_node(scene_node)
        self.nodeRemoved.emit(node_id)
        self.edgeChanged.emit()

    def connect_edge(self, edge: Edge) -> None:
        """Pre-check the cycle and mutate model + scene atomically."""
        if self._graph is None:
            return
        # Pre-check via model — lib's own cycle detection has a dangling-state quirk.
        if self._graph.has_cycle_if_added(edge):
            raise CycleError(
                f"edge {edge.src_node_id}.{edge.src_port} -> "
                f"{edge.dst_node_id}.{edge.dst_port} would create a cycle"
            )
        self._graph.connect(edge)
        self._spawn_scene_edge(edge)
        self.edgeChanged.emit()

    def disconnect_edge(self, edge: Edge) -> None:
        if self._graph is None:
            return
        self._graph.disconnect(edge)
        self._remove_scene_edge(edge)
        self.edgeChanged.emit()

    def set_tap(self, node_id: str, port: str = "out") -> None:
        if self._graph is None:
            return
        self._graph.set_tap(node_id, port)
        self.tapPortChanged.emit(node_id, port)

    # --- introspection helpers (used by tests) ------------------------

    def has_source_node(self) -> bool:
        return self._source_scene_node is not None

    def scene_node_count(self) -> int:
        return len(self._scene.nodes)

    def scene_node_for(self, node_id: str):
        return self._scene_nodes.get(node_id)

    def scene_input_port_count(self, node_id: str) -> int:
        node = self._scene_nodes.get(node_id)
        if node is None:
            return 0
        return len(node[PortType.input])

    # --- rendering ------------------------------------------------------

    def _rerender(self) -> None:
        # Wipe scene.
        self._scene.clear_scene()
        self._scene_nodes.clear()
        self._source_scene_node = None

        # Re-spawn Source.
        self._source_scene_node = self._scene.create_node(_SourceModel)

        if self._graph is None:
            return

        # Spawn nodes.
        for node in self._graph.nodes.values():
            self._spawn_scene_node(node)

        # Spawn edges.
        for edge in self._graph.edges:
            self._spawn_scene_edge(edge)

    def _spawn_scene_node(self, node: Node) -> None:
        model_cls = self._ensure_spec_registered(node.spec)
        self._suppress_signal_sync = True
        try:
            scene_node = self._scene.create_node(model_cls)
        finally:
            self._suppress_signal_sync = False
        self._scene_nodes[node.node_id] = scene_node
        if node.pos != (0.0, 0.0):
            scene_node.position = node.pos

    def _resolve_scene_node(self, node_id: str):
        if node_id == SOURCE_ID:
            return self._source_scene_node
        return self._scene_nodes.get(node_id)

    def _src_port_index(self, edge: Edge) -> int:
        if edge.src_node_id == SOURCE_ID:
            return SOURCE_PORTS.index(edge.src_port)
        return 0

    def _dst_port_index(self, edge: Edge) -> int:
        # SOURCE_ID has no input ports; this is unreachable for valid edges.
        node = self._graph.nodes[edge.dst_node_id]
        return node.spec.inputs.index(edge.dst_port)

    def _spawn_scene_edge(self, edge: Edge) -> None:
        src_node = self._resolve_scene_node(edge.src_node_id)
        dst_node = self._resolve_scene_node(edge.dst_node_id)
        if src_node is None or dst_node is None:
            return
        src_port_idx = self._src_port_index(edge)
        dst_port_idx = self._dst_port_index(edge)
        self._suppress_signal_sync = True
        try:
            self._scene.create_connection(
                src_node[PortType.output][src_port_idx],
                dst_node[PortType.input][dst_port_idx],
            )
        except qne.ConnectionCycleFailure:
            # Belt-and-braces: lib raised on its own cycle check after our
            # pre-check; clean up any dangling connection it may have stashed.
            self._cleanup_orphan_connections(dst_node, dst_port_idx)
            raise CycleError(
                f"edge {edge.src_node_id}.{edge.src_port} -> "
                f"{edge.dst_node_id}.{edge.dst_port} would create a cycle"
            ) from None
        finally:
            self._suppress_signal_sync = False

    def _remove_scene_edge(self, edge: Edge) -> None:
        dst_node = self._resolve_scene_node(edge.dst_node_id)
        if dst_node is None:
            return
        dst_port_idx = self._dst_port_index(edge)
        port = dst_node[PortType.input][dst_port_idx]
        for conn in list(port.connections):
            src = conn.get_node(PortType.output)
            if src is self._resolve_scene_node(edge.src_node_id):
                self._suppress_signal_sync = True
                try:
                    self._scene.delete_connection(conn)
                finally:
                    self._suppress_signal_sync = False
                return

    def _cleanup_orphan_connections(self, dst_node, dst_port_idx: int) -> None:
        """Walk the dst port and drop any connection that lacks a valid src."""
        port = dst_node[PortType.input][dst_port_idx]
        for conn in list(port.connections):
            try:
                conn.get_node(PortType.output)
            except (AttributeError, KeyError):
                self._scene.delete_connection(conn)

    # --- lib-signal sync (user-drag on canvas) -------------------------

    def _scene_node_to_graph_id(self, scene_node) -> str | None:
        """Reverse-lookup: scene node -> graph node_id (or SOURCE_ID)."""
        if scene_node is self._source_scene_node:
            return SOURCE_ID
        for node_id, sn in self._scene_nodes.items():
            if sn is scene_node:
                return node_id
        return None

    def _scene_port_name(self, scene_node, port_type, port_idx: int) -> str | None:
        graph_id = self._scene_node_to_graph_id(scene_node)
        if graph_id == SOURCE_ID:
            return SOURCE_PORTS[port_idx] if port_type == PortType.output else None
        if graph_id is None:
            return None
        node = self._graph.nodes[graph_id]
        if port_type == PortType.output:
            return "out"
        return node.spec.inputs[port_idx]

    def _connection_to_edge(self, conn) -> Edge | None:
        src_scene = conn.get_node(PortType.output)
        dst_scene = conn.get_node(PortType.input)
        src_id = self._scene_node_to_graph_id(src_scene)
        dst_id = self._scene_node_to_graph_id(dst_scene)
        if src_id is None or dst_id is None:
            return None
        src_port = self._scene_port_name(
            src_scene, PortType.output, conn.get_port_index(PortType.output)
        )
        dst_port = self._scene_port_name(
            dst_scene, PortType.input, conn.get_port_index(PortType.input)
        )
        if src_port is None or dst_port is None:
            return None
        return Edge(src_id, src_port, dst_id, dst_port)

    def _on_lib_connection_created(self, conn) -> None:
        """User dragged a wire on the canvas — mirror into the model."""
        if self._suppress_signal_sync or self._graph is None:
            return
        edge = self._connection_to_edge(conn)
        if edge is None:
            return
        if self._graph.has_cycle_if_added(edge):
            self._suppress_signal_sync = True
            try:
                self._scene.delete_connection(conn)
            finally:
                self._suppress_signal_sync = False
            return
        try:
            self._graph.connect(edge)
        except (CycleError, ValueError, KeyError):
            self._suppress_signal_sync = True
            try:
                self._scene.delete_connection(conn)
            finally:
                self._suppress_signal_sync = False
            return
        self.edgeChanged.emit()

    def _on_lib_connection_deleted(self, conn) -> None:
        """User deleted a wire on the canvas — mirror into the model."""
        if self._suppress_signal_sync or self._graph is None:
            return
        edge = self._connection_to_edge(conn)
        if edge is None:
            return
        if edge in self._graph.edges:
            self._graph.disconnect(edge)
            self.edgeChanged.emit()

    def _on_lib_node_created(self, scene_node) -> None:
        """User created a node via the lib's right-click 'Add Node' menu."""
        if self._suppress_signal_sync or self._graph is None:
            return
        # Source is a singleton; ignore lib-side creates of it.
        if isinstance(scene_node.model, _SourceModel):
            return
        cls_name = type(scene_node.model).__name__
        spec = self._spec_by_class.get(cls_name)
        if spec is None:
            return
        node = Node(spec=spec, params=spec.param_model())
        # Read the position the lib placed the node at (ContextMenuEvent
        # passes the mouse position to scene.create_node).
        try:
            pos = scene_node.position
            node.pos = (pos.x(), pos.y())
        except Exception:
            pass
        self._graph.add_node(node)
        self._scene_nodes[node.node_id] = scene_node
        self.nodeAdded.emit(node.node_id)

    def _on_scene_selection_changed(self) -> None:
        """Translate scene selection into a graph node_id (or empty)."""
        selected = self._scene.selectedItems()
        for item in selected:
            scene_node = getattr(item, "node", None)
            if scene_node is None:
                continue
            graph_id = self._scene_node_to_graph_id(scene_node)
            if graph_id is not None and graph_id != SOURCE_ID:
                self.selectionChanged.emit(graph_id)
                return
        self.selectionChanged.emit("")

