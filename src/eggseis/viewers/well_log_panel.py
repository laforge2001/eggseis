"""Well log-curve side panel — renders a single log alongside the section."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

from eggseis.data.well import Well


class WellLogPanel(QWidget):
    """Side panel showing a selected log curve aligned with the section's time axis.

    Public surface:
      - set_well(well, sample_rate_ms): wire to a well, populate dropdown.
      - clear(): remove the active well + plot.
      - selectedCurveChanged(name): emitted when the dropdown changes.
    """

    selectedCurveChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self._title = QLabel("Well: (none)")
        self._title.setStyleSheet("QLabel { font-size: 11px; padding: 2px; }")
        layout.addWidget(self._title)

        self._curve_picker = QComboBox()
        self._curve_picker.currentTextChanged.connect(self._on_curve_changed)
        layout.addWidget(self._curve_picker)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.invertY(True)  # match section viewer (time grows downward)
        self._plot.setLabel("left", "Time (samples)")
        self._plot.setLabel("bottom", "Value")
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._curve_item = pg.PlotDataItem(pen=pg.mkPen("#3399ff", width=1.5))
        self._plot.addItem(self._curve_item)
        layout.addWidget(self._plot, stretch=1)

        self._well: Well | None = None
        self._sample_rate_ms: float = 1.0

    def set_well(self, well: Well, sample_rate_ms: float = 1.0) -> None:
        self._well = well
        self._sample_rate_ms = sample_rate_ms
        self._title.setText(f"Well: {well.name}")
        self._curve_picker.blockSignals(True)
        self._curve_picker.clear()
        for name in well.logs.keys():
            self._curve_picker.addItem(name)
        self._curve_picker.blockSignals(False)
        if self._curve_picker.count() > 0:
            self._curve_picker.setCurrentIndex(0)
            self._render_curve(self._curve_picker.currentText())

    def clear(self) -> None:
        self._well = None
        self._title.setText("Well: (none)")
        self._curve_picker.clear()
        self._curve_item.setData(x=[], y=[])

    def selected_curve(self) -> str:
        return self._curve_picker.currentText()

    def _on_curve_changed(self, name: str) -> None:
        if not name:
            return
        self._render_curve(name)
        self.selectedCurveChanged.emit(name)

    def _render_curve(self, name: str) -> None:
        if self._well is None or name not in self._well.logs:
            self._curve_item.setData(x=[], y=[])
            return
        values = np.asarray(self._well.logs[name], dtype=np.float32)
        # MD axis from deviation column 0; assume time-domain (per Well.domain="time_ms").
        md = self._well.deviation[:, 0]
        y = md / self._sample_rate_ms
        # Mask out NaN values from null-replaced log entries.
        mask = ~np.isnan(values)
        self._curve_item.setData(x=values[mask], y=y[mask])
