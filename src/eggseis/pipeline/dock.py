"""PipelineDock — list-style UI for the M5 linear pipeline."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


class _NodeRow(QWidget):
    def __init__(self, node: Node, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.enable_checkbox = QCheckBox(self)
        self.enable_checkbox.setChecked(node.enabled)
        self.label = QLabel(node.spec.name, self)
        self.tap_radio = QRadioButton(self)
        self.tap_radio.setEnabled(node.enabled)
        layout.addWidget(self.enable_checkbox)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.tap_radio)


class _SourceRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.label = QLabel("Source (raw amplitude)", self)
        self.tap_radio = QRadioButton(self)
        self.tap_radio.setChecked(True)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.tap_radio)


class PipelineDock(QDockWidget):
    pipelineChanged = Signal()
    tapChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, param_widget_factory=None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None
        self._param_widget_factory = param_widget_factory
        self._param_widgets: dict[str, QWidget] = {}
        self._row_widgets: dict[str, _NodeRow] = {}
        self._source_row: _SourceRow | None = None
        self._tap_group = QButtonGroup(self)
        self._tap_group.setExclusive(True)

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

    @property
    def source_tap_radio(self) -> QRadioButton | None:
        return self._source_row.tap_radio if self._source_row else None

    def row_widget(self, node_id: str) -> _NodeRow | None:
        return self._row_widgets.get(node_id)

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

    def remove_node(self, node_id: str) -> None:
        if self._pipeline is None:
            return
        if node_id == SOURCE_ID:
            return
        self._pipeline.remove(node_id)
        self._refresh()
        self.pipelineChanged.emit()

    def move_row(self, from_row: int, to_row: int) -> None:
        """Move list row from_row -> to_row. Both must be > 0; row 0 is Source."""
        if self._pipeline is None or from_row <= 0 or to_row <= 0:
            return
        node_id = self.list_widget.item(from_row).data(Qt.UserRole)
        target_index_in_pipeline = to_row - 1
        self._pipeline.move(node_id, target_index_in_pipeline)
        self._refresh()
        self.pipelineChanged.emit()

    def _refresh(self) -> None:
        for w in list(self._param_widgets.values()):
            self.param_host.removeWidget(w)
            w.deleteLater()
        self._param_widgets.clear()
        for btn in list(self._tap_group.buttons()):
            self._tap_group.removeButton(btn)
        self.list_widget.clear()
        self._row_widgets.clear()

        if self._pipeline is None:
            return

        # Source row.
        src_item = QListWidgetItem("Source (raw amplitude)", self.list_widget)
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._source_row = _SourceRow()
        src_item.setSizeHint(self._source_row.sizeHint())
        self.list_widget.setItemWidget(src_item, self._source_row)
        self._tap_group.addButton(self._source_row.tap_radio)
        self._source_row.tap_radio.toggled.connect(
            lambda on: self._on_tap_toggled(SOURCE_ID, on)
        )

        for node in self._pipeline.nodes:
            self._append_node_row(node)
            if self._param_widget_factory is not None:
                widget = self._param_widget_factory(node)
                if widget is not None:
                    self.param_host.addWidget(widget)
                    self._param_widgets[node.node_id] = widget

        self._sync_tap_radio_from_pipeline()

    def _append_node_row(self, node: Node) -> None:
        item = QListWidgetItem(node.spec.name, self.list_widget)
        item.setData(Qt.UserRole, node.node_id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        item.setFlags(flags)
        row = _NodeRow(node)
        item.setSizeHint(row.sizeHint())
        self.list_widget.setItemWidget(item, row)
        self._row_widgets[node.node_id] = row
        self._tap_group.addButton(row.tap_radio)
        row.enable_checkbox.toggled.connect(
            lambda on, nid=node.node_id: self._on_enable_toggled(nid, on)
        )
        row.tap_radio.toggled.connect(
            lambda on, nid=node.node_id: self._on_tap_toggled(nid, on)
        )

    def _on_enable_toggled(self, node_id: str, on: bool) -> None:
        if self._pipeline is None:
            return
        self._pipeline.set_enabled(node_id, on)
        row = self._row_widgets.get(node_id)
        if row is not None:
            row.tap_radio.setEnabled(on)
        self._sync_tap_radio_from_pipeline()
        self.pipelineChanged.emit()

    def _on_tap_toggled(self, node_id: str, on: bool) -> None:
        if not on or self._pipeline is None:
            return
        self._pipeline.set_tap(node_id)
        if self._pipeline.tap_node_id != node_id:
            self._sync_tap_radio_from_pipeline()
        self.tapChanged.emit(self._pipeline.tap_node_id)

    def _sync_tap_radio_from_pipeline(self) -> None:
        if self._pipeline is None:
            return
        target = self._pipeline.tap_node_id
        if target == SOURCE_ID and self._source_row is not None:
            self._source_row.tap_radio.setChecked(True)
            return
        row = self._row_widgets.get(target)
        if row is not None:
            row.tap_radio.setChecked(True)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.list_widget.item(row)
        node_id = item.data(Qt.UserRole)
        if node_id == SOURCE_ID or node_id not in self._param_widgets:
            self.param_host.setCurrentWidget(self._empty_panel)
            return
        self.param_host.setCurrentWidget(self._param_widgets[node_id])
