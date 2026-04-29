"""PipelineDock — list-style UI for the M5 linear pipeline.

Layout (Task 21 minimum):

    +-----------------------------+
    | Source (raw amplitude)      |
    +-----------------------------+

Subsequent tasks add: enable checkbox + tap radio per node row, the
"+ Add plugin" button, the selection-driven param panel, drag-to-reorder.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


class PipelineDock(QDockWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None

        body = QWidget(self)
        layout = QVBoxLayout(body)

        self.list_widget = QListWidget(body)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_button = QPushButton("+ Add plugin", body)
        layout.addWidget(self.add_button)

        self.param_host = QStackedWidget(body)
        layout.addWidget(self.param_host, stretch=1)

        self.setWidget(body)

    def bind(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._refresh()

    def _refresh(self) -> None:
        self.list_widget.clear()
        if self._pipeline is None:
            return
        src_item = QListWidgetItem("Source (raw amplitude)")
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.list_widget.addItem(src_item)
        for node in self._pipeline.nodes:
            self._append_node_row(node)

    def _append_node_row(self, node: Node) -> None:
        item = QListWidgetItem(node.spec.name)
        item.setData(Qt.UserRole, node.node_id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        item.setFlags(flags)
        self.list_widget.addItem(item)
