"""ParamDock tests — headless Qt via pytest-qt + offscreen platform."""

from __future__ import annotations


def test_set_plugin_with_params_seeds_initial_values(qtbot, linear_spec):
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    dock.set_plugin(linear_spec, params=linear_spec.param_model(scale=4.2))
    assert dock._widgets["scale"].value == 4.2


def test_set_plugin_default_seeds_from_spec(qtbot, linear_spec):
    from eggseis.widgets.param_dock import ParamDock

    dock = ParamDock()
    qtbot.addWidget(dock)
    dock.set_plugin(linear_spec)
    # linear_spec default for scale is 1.0
    assert dock._widgets["scale"].value == 1.0
