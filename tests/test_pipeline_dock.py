"""PipelineDock tests — headless Qt via pytest-qt + offscreen platform."""

from __future__ import annotations


def test_source_row_appears_first_after_bind(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    dock.bind(make_pipeline())  # empty pipeline
    assert dock.list_widget.count() == 1
    assert "source" in dock.list_widget.item(0).text().lower()


def test_bind_renders_user_added_nodes(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)
    assert dock.list_widget.count() == 3  # Source + 2 nodes


def test_add_plugin_appends_node(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline()
    dock.bind(p)

    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.add_plugin(linear_spec)

    assert dock.list_widget.count() == 2  # Source + new node
    assert len(p.nodes) == 1
    assert p.nodes[0].spec is linear_spec


def test_select_row_swaps_param_panel(qtbot, linear_spec, make_pipeline):
    from PySide6.QtWidgets import QLabel

    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock(param_widget_factory=lambda node: QLabel(node.node_id))
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)

    # Select first user node (row 1; row 0 is Source).
    dock.list_widget.setCurrentRow(1)
    assert isinstance(dock.param_host.currentWidget(), QLabel)
    assert dock.param_host.currentWidget().text() == p.nodes[0].node_id

    # Switch to second.
    dock.list_widget.setCurrentRow(2)
    assert dock.param_host.currentWidget().text() == p.nodes[1].node_id


def test_source_row_shows_empty_param_panel(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock(param_widget_factory=lambda node: None)
    qtbot.addWidget(dock)
    dock.bind(make_pipeline(linear_spec))
    dock.list_widget.setCurrentRow(0)  # Source
    assert dock.param_host.currentWidget() is dock._empty_panel
