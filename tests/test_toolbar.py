"""Primary toolbar — QtAwesome icons + project-state gating."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qtawesome")


@pytest.fixture
def actions(qtbot):
    from PySide6.QtGui import QAction
    return {
        name: QAction(name)
        for name in (
            "open", "save", "import_survey", "import_horizon",
            "import_well", "add_plugin", "export_volume",
        )
    }


@pytest.fixture
def toolbar(qtbot, actions):
    from eggseis.widgets.toolbar import PrimaryToolbar

    tb = PrimaryToolbar(actions)
    qtbot.addWidget(tb)
    return tb


def test_buttons_disabled_when_no_project(toolbar):
    toolbar.set_project_loaded(False)
    assert not toolbar._action_for("save").isEnabled()
    assert not toolbar._action_for("import_survey").isEnabled()
    assert not toolbar._action_for("export_volume").isEnabled()
    # open is always enabled
    assert toolbar._action_for("open").isEnabled()


def test_buttons_enabled_when_project_loaded(toolbar):
    toolbar.set_project_loaded(True)
    for name in (
        "save", "import_survey", "import_horizon", "import_well", "add_plugin", "export_volume"
    ):
        assert toolbar._action_for(name).isEnabled()


def test_open_action_triggers_passed_action(toolbar, actions, qtbot):
    received = []
    actions["open"].triggered.connect(lambda: received.append(True))
    actions["open"].trigger()
    assert received == [True]
