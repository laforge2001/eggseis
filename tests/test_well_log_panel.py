"""WellLogPanel — log curve display."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.data.well import Well


@pytest.fixture
def basic_well():
    md = np.array([0.0, 100.0, 200.0], dtype=np.float32)
    deviation = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    return Well(
        name="Well-X",
        deviation=deviation,
        logs={"GR": np.array([55.0, 60.0, 70.0], dtype=np.float32),
              "RHOB": np.array([2.4, 2.45, 2.5], dtype=np.float32)},
        markers=[],
        surface_xy=(0.0, 0.0),
    )


def test_set_well_populates_picker(qtbot, basic_well):
    from eggseis.viewers.well_log_panel import WellLogPanel
    panel = WellLogPanel()
    qtbot.addWidget(panel)
    panel.set_well(basic_well, sample_rate_ms=4.0)
    assert panel._curve_picker.count() == 2
    items = [panel._curve_picker.itemText(i) for i in range(panel._curve_picker.count())]
    assert "GR" in items
    assert "RHOB" in items


def test_first_curve_auto_selected(qtbot, basic_well):
    from eggseis.viewers.well_log_panel import WellLogPanel
    panel = WellLogPanel()
    qtbot.addWidget(panel)
    panel.set_well(basic_well, sample_rate_ms=4.0)
    assert panel.selected_curve() == "GR"


def test_change_curve_emits_signal(qtbot, basic_well):
    from eggseis.viewers.well_log_panel import WellLogPanel
    panel = WellLogPanel()
    qtbot.addWidget(panel)
    panel.set_well(basic_well, sample_rate_ms=4.0)
    received = []
    panel.selectedCurveChanged.connect(received.append)
    panel._curve_picker.setCurrentText("RHOB")
    assert received[-1] == "RHOB"


def test_clear_resets_panel(qtbot, basic_well):
    from eggseis.viewers.well_log_panel import WellLogPanel
    panel = WellLogPanel()
    qtbot.addWidget(panel)
    panel.set_well(basic_well, sample_rate_ms=4.0)
    panel.clear()
    assert panel._curve_picker.count() == 0
    assert panel._well is None


def test_renders_curve_data_skipping_nans(qtbot, basic_well):
    """NaN values in the log array shouldn't end up in the plot data."""
    from eggseis.viewers.well_log_panel import WellLogPanel
    basic_well.logs["GR"] = np.array([55.0, np.nan, 70.0], dtype=np.float32)
    panel = WellLogPanel()
    qtbot.addWidget(panel)
    panel.set_well(basic_well, sample_rate_ms=4.0)
    x, _y = panel._curve_item.getData()
    assert len(x) == 2
    assert 55.0 in x and 70.0 in x
