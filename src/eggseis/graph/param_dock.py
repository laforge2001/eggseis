"""GraphParamDock — selection-driven per-node parameter editor.

A QStackedWidget of M5-style ParamDocks, one per graph node. The active
widget switches when the canvas raises selectionChanged. Forwards
parameter changes upstream as `paramsChanged(node_id, params_model)`
so MainWindow can route them into `Graph.set_params` and re-tap.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDockWidget, QStackedWidget, QWidget

from eggseis.graph.model import Graph
from eggseis.widgets.param_dock import ParamDock


class GraphParamDock(QDockWidget):
    paramsChanged = Signal(str, object)  # node_id, pydantic BaseModel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Parameters", parent)
        self._graph: Graph | None = None
        self._inner: dict[str, ParamDock] = {}
        self._stack = QStackedWidget(self)
        self._empty = QWidget(self)
        self._stack.addWidget(self._empty)
        self.setWidget(self._stack)
        self._current_node_id: str | None = None

    # --- public API ---------------------------------------------------

    def bind(self, graph: Graph) -> None:
        """Attach the graph and rebuild inner ParamDocks for current nodes.

        Rebinding wipes any prior graph's widgets — node_ids are UUIDs so
        collisions are unlikely but a stale widget bound to the old node's
        spec would otherwise survive the diff in `refresh()`.
        """
        for inner in self._inner.values():
            self._stack.removeWidget(inner)
            inner.deleteLater()
        self._inner.clear()
        self._current_node_id = None
        self._stack.setCurrentWidget(self._empty)
        self._graph = graph
        self.refresh()

    def refresh(self) -> None:
        """Re-sync inner widgets with current graph state.

        Adds new nodes' widgets, removes widgets for deleted nodes, and
        clears the current selection if the active node is gone.
        """
        if self._graph is None:
            return
        existing_ids = set(self._inner.keys())
        graph_ids = set(self._graph.nodes.keys())

        # Remove widgets for deleted nodes.
        for stale in existing_ids - graph_ids:
            inner = self._inner.pop(stale)
            self._stack.removeWidget(inner)
            inner.deleteLater()

        # Spawn widgets for new nodes.
        for new_id in graph_ids - existing_ids:
            node = self._graph.nodes[new_id]
            inner = ParamDock()
            inner.set_plugin(node.spec, params=node.params)
            inner.paramsChanged.connect(
                lambda params, nid=new_id: self.paramsChanged.emit(nid, params)
            )
            self._inner[new_id] = inner
            self._stack.addWidget(inner)

        # If currently shown node is gone, fall back to empty.
        if self._current_node_id is not None and self._current_node_id not in graph_ids:
            self._current_node_id = None
            self._stack.setCurrentWidget(self._empty)

    def show_node(self, node_id: str | None) -> None:
        """Switch the active inner widget. None or unknown id displays empty."""
        if node_id is None or self._graph is None or node_id not in self._inner:
            self._current_node_id = None
            self._stack.setCurrentWidget(self._empty)
            return
        self._current_node_id = node_id
        self._stack.setCurrentWidget(self._inner[node_id])

    def current_node_id(self) -> str | None:
        return self._current_node_id

    def inner_dock_for(self, node_id: str) -> ParamDock | None:
        return self._inner.get(node_id)
