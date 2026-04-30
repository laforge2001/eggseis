"""Modeless params popup — opens on canvas node double-click.

Wraps the M5-style ParamDock in a QDialog so users can edit a single
node's parameters without a permanent dock taking screen real estate.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from eggseis.graph.model import Node
from eggseis.widgets.param_dock import ParamDock


class NodeParamsPopup(QDialog):
    paramsChanged = Signal(str, object)  # node_id, BaseModel

    def __init__(self, node: Node, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._node_id = node.node_id
        self.setWindowTitle(f"Parameters — {node.spec.name}")
        self.setWindowFlag(Qt.Tool, True)  # Floating utility window
        self.setModal(False)
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self._inner = ParamDock()
        self._inner.set_plugin(node.spec, params=node.params)
        self._inner.paramsChanged.connect(
            lambda params: self.paramsChanged.emit(self._node_id, params)
        )
        layout.addWidget(self._inner)

    @property
    def node_id(self) -> str:
        return self._node_id
