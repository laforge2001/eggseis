"""Slice navigator: axis selector + bounded spinbox."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from eggseis.axes import AXES, Axis
from eggseis.data import SurveyGeometry


class SliceNavigator(QWidget):
    sliceChanged = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)

        self.axis = QComboBox()
        self.axis.addItems(list(AXES))
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
        lo, hi, step = self._geom.range_for(axis)
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
        """Move the spinbox by `direction * singleStep`. QSpinBox clamps to range."""
        if not self.spinbox.isEnabled():
            return
        self.spinbox.setValue(self.spinbox.value() + direction * self.spinbox.singleStep())

    def set_axis(self, axis: str) -> None:
        if axis not in AXES:
            raise ValueError(f"Unknown axis {axis!r}; expected one of {AXES}")
        if self._geom is None:
            return  # shortcuts may fire before any project is loaded
        self.axis.setCurrentText(axis)

    def set_axis_and_index(self, axis: Axis | str, index: int) -> None:
        """Switch axis and jump to the given index.

        The combo's currentTextChanged handler reseeds the spinbox to the
        axis lower bound; we then write the requested index, which the
        spinbox clamps to its valid range and emits sliceChanged.
        """
        axis = Axis(axis)
        if axis not in AXES:
            raise ValueError(f"Unknown axis {axis!r}; expected one of {AXES}")
        if self._geom is None:
            return
        self.axis.setCurrentText(axis)
        self.spinbox.setValue(int(index))
