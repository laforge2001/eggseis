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
