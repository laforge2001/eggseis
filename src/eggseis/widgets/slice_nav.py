"""Slice navigator: axis selector + bounded spinbox."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from eggseis.data import SurveyGeometry

AXES: tuple[str, ...] = ("inline", "xline", "timeslice")


class SliceNavigator(QWidget):
    sliceChanged = Signal(str, int)  # axis, index

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)

        self.axis = QComboBox()
        self.axis.addItems(AXES)
        self.spinbox = QSpinBox()
        self.spinbox.setEnabled(False)

        layout.addWidget(QLabel("Axis:"))
        layout.addWidget(self.axis)
        layout.addWidget(QLabel("Index:"))
        layout.addWidget(self.spinbox)
        layout.addStretch(1)

        self._geom: SurveyGeometry | None = None
        self.axis.currentTextChanged.connect(self._on_axis_changed)
        self.spinbox.valueChanged.connect(self._emit_change)

    def set_geometry(self, geom: SurveyGeometry) -> None:
        self._geom = geom
        self.spinbox.setEnabled(True)
        self._on_axis_changed(self.axis.currentText())

    def _on_axis_changed(self, axis: str) -> None:
        if self._geom is None:
            return
        g = self._geom
        if axis == "inline":
            lo, hi, step = g.inline_min, g.inline_max, g.inline_step
        elif axis == "xline":
            lo, hi, step = g.xline_min, g.xline_max, g.xline_step
        else:
            lo, hi, step = 0, g.n_samples - 1, 1
        self.spinbox.blockSignals(True)
        self.spinbox.setRange(lo, hi)
        self.spinbox.setSingleStep(step)
        self.spinbox.setValue(lo)
        self.spinbox.blockSignals(False)
        self._emit_change()

    def _emit_change(self) -> None:
        if self._geom is not None:
            self.sliceChanged.emit(self.axis.currentText(), self.spinbox.value())

    def step(self, direction: int) -> None:
        """Move the spinbox by `direction * singleStep`. Clamped to range."""
        if not self.spinbox.isEnabled():
            return
        new_val = self.spinbox.value() + direction * self.spinbox.singleStep()
        new_val = max(self.spinbox.minimum(), min(self.spinbox.maximum(), new_val))
        self.spinbox.setValue(new_val)

    def set_axis(self, axis: str) -> None:
        if axis in AXES:
            self.axis.setCurrentText(axis)
