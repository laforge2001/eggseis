"""PipelineDock — list-style UI for the M5 linear pipeline.

Layout (Task 21 minimum):

    +-----------------------------+
    | Source (raw amplitude)      |
    +-----------------------------+

Subsequent tasks add: enable checkbox + tap radio per node row, the
"+ Add plugin" button, the selection-driven param panel, drag-to-reorder.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    pipelineChanged = Signal()
    tapChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, param_widget_factory=None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None
        self._param_widget_factory = param_widget_factory
        self._param_widgets: dict[str, QWidget] = {}

        body = QWidget(self)
        layout = QVBoxLayout(body)

        self.list_widget = QListWidget(body)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_button = QPushButton("+ Add plugin", body)
        layout.addWidget(self.add_button)

        self.param_host = QStackedWidget(body)
        self._empty_panel = QWidget(body)
        self.param_host.addWidget(self._empty_panel)
        layout.addWidget(self.param_host, stretch=1)

        self.setWidget(body)

    def bind(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._refresh()

    def add_plugin(self, spec) -> None:
        if self._pipeline is None:
            return
        node = Node(spec=spec, params=spec.param_model())
        self._pipeline.append(node)
        self._refresh()
        self.pipelineChanged.emit()

    def _refresh(self) -> None:
        self.list_widget.clear()
        for w in list(self._param_widgets.values()):
            self.param_host.removeWidget(w)
            w.deleteLater()
        self._param_widgets.clear()

        if self._pipeline is None:
            return

        src_item = QListWidgetItem("Source (raw amplitude)")
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.list_widget.addItem(src_item)

        for node in self._pipeline.nodes:
            self._append_node_row(node)
            if self._param_widget_factory is not None:
                widget = self._param_widget_factory(node)
                if widget is not None:
                    self.param_host.addWidget(widget)
                    self._param_widgets[node.node_id] = widget

    def _append_node_row(self, node: Node) -> None:
        item = QListWidgetItem(node.spec.name)
        item.setData(Qt.UserRole, node.node_id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        item.setFlags(flags)
        self.list_widget.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.list_widget.item(row)
        node_id = item.data(Qt.UserRole)
        if node_id == SOURCE_ID or node_id not in self._param_widgets:
            self.param_host.setCurrentWidget(self._empty_panel)
            return
        self.param_host.setCurrentWidget(self._param_widgets[node_id])
