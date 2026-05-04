"""HeaderEditorDialog basic interactions."""

from __future__ import annotations

from eggseis.data import SurveyGeometry
from eggseis.widgets.header_editor import HeaderEditorDialog


def _geom() -> SurveyGeometry:
    return SurveyGeometry(
        inline_min=100, inline_max=131, inline_step=1,
        xline_min=300, xline_max=323, xline_step=1,
        n_samples=96, sample_rate_ms=4.0,
    )


def test_dialog_constructs_with_geometry(qtbot):
    g = _geom()
    dlg = HeaderEditorDialog(g)
    qtbot.addWidget(dlg)
    assert dlg._inline_min.value() == 100
    assert dlg._xline_min.value() == 300


def test_apply_emits_overridden_geometry(qtbot):
    g = _geom()
    dlg = HeaderEditorDialog(g)
    qtbot.addWidget(dlg)
    received = []
    dlg.geometryOverridden.connect(received.append)
    dlg._inline_min.setValue(200)
    dlg._inline_max.setValue(231)
    dlg._on_apply()
    assert len(received) == 1
    assert received[0].inline_min == 200


def test_reset_restores_original_values(qtbot):
    g = _geom()
    dlg = HeaderEditorDialog(g)
    qtbot.addWidget(dlg)
    dlg._inline_min.setValue(500)
    dlg._on_reset()
    assert dlg._inline_min.value() == 100


def test_apply_with_invalid_range_does_nothing(qtbot):
    """Invalid inline_max < inline_min should be a silent no-op."""
    g = _geom()
    dlg = HeaderEditorDialog(g)
    qtbot.addWidget(dlg)
    received = []
    dlg.geometryOverridden.connect(received.append)
    dlg._inline_min.setValue(200)
    dlg._inline_max.setValue(50)  # invalid: max < min
    dlg._on_apply()
    assert received == []
