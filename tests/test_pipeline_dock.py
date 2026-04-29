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


def test_enable_checkbox_toggles_node(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        row_widget.enable_checkbox.setChecked(False)
    assert p.nodes[0].enabled is False


def test_disable_greys_tap_radio(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    assert row_widget.tap_radio.isEnabled() is True
    row_widget.enable_checkbox.setChecked(False)
    assert row_widget.tap_radio.isEnabled() is False


def test_clicking_tap_radio_emits_tapChanged(qtbot, linear_spec, make_pipeline):  # noqa: N802
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    with qtbot.waitSignal(dock.tapChanged, timeout=1000) as blocker:
        row_widget.tap_radio.setChecked(True)
    (new_tap,) = blocker.args
    assert new_tap == p.nodes[0].node_id
    assert p.tap_node_id == p.nodes[0].node_id


def test_source_tap_radio_present_and_default(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)
    assert dock.source_tap_radio.isChecked() is True


def test_remove_node_via_method(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)

    target_id = p.nodes[0].node_id
    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.remove_node(target_id)
    assert len(p.nodes) == 1
    assert p.nodes[0].node_id != target_id


def test_drag_reorder_updates_pipeline_order(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec, linear_spec)
    dock.bind(p)
    original_ids = [n.node_id for n in p.nodes]

    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.move_row(3, 1)

    new_ids = [n.node_id for n in p.nodes]
    assert new_ids == [original_ids[2], original_ids[0], original_ids[1]]
