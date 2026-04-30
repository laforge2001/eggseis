"""ParamDock tests — headless Qt via pytest-qt + offscreen platform."""

from __future__ import annotations


def test_set_plugin_with_params_seeds_initial_values(qtbot, linear_spec):
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    dock.set_plugin(linear_spec, params=linear_spec.param_model(scale=4.2))
    assert dock.current_params().scale == 4.2


def test_set_plugin_default_seeds_from_spec(qtbot, linear_spec):
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    dock.set_plugin(linear_spec)
    # linear_spec default for scale is 1.0
    assert dock.current_params().scale == 1.0


def test_set_plugin_with_params_does_not_emit_initial(qtbot, linear_spec):
    """When caller supplies params, ParamDock must not fire paramsChanged on init.
    Otherwise dock factory rebuilds trigger redundant pipeline recomputes."""
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    seen = []
    dock.paramsChanged.connect(lambda p: seen.append(p))
    dock.set_plugin(linear_spec, params=linear_spec.param_model(scale=2.0))
    assert seen == []  # no initial emit


def test_set_plugin_without_params_emits_initial(qtbot, linear_spec):
    """Legacy path: when no params supplied, ParamDock fires once with defaults."""
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    seen = []
    dock.paramsChanged.connect(lambda p: seen.append(p))
    dock.set_plugin(linear_spec)
    assert len(seen) == 1
    assert seen[0].scale == 1.0
