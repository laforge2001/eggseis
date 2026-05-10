"""Header editor — modeless QDialog for re-interpreting survey geometry.

v1.0 scope: edit inline/xline range overrides on the in-memory
SurveyGeometry. Does NOT write back to the MDIO file. Re-import from
SEG-Y with corrected byte locations is deferred to a later milestone.
"""

from __future__ import annotations

from dataclasses import replace as _dc_replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from eggseis.data import SurveyGeometry


class HeaderEditorDialog(QDialog):
    """Edit in-memory geometry overrides for the active survey."""

    geometryOverridden = Signal(object)  # SurveyGeometry
    geometryReset = Signal()

    def __init__(self, geometry: SurveyGeometry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Trace Headers")
        self.setWindowFlag(Qt.Tool, True)
        self.setModal(False)
        self._original = geometry
        self._build_ui(geometry)

    def _build_ui(self, g: SurveyGeometry) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "Edit inline/xline range overrides on the active survey. "
            "Changes are in-memory only — the MDIO file is not modified.\n"
            "(SEG-Y header byte-location reimport is deferred to a future "
            "milestone.)"
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        form = QFormLayout()
        self._inline_min = QSpinBox()
        self._inline_min.setRange(0, 100_000)
        self._inline_min.setValue(g.inline_min)
        form.addRow("Inline min:", self._inline_min)

        self._inline_max = QSpinBox()
        self._inline_max.setRange(0, 100_000)
        self._inline_max.setValue(g.inline_max)
        form.addRow("Inline max:", self._inline_max)

        self._xline_min = QSpinBox()
        self._xline_min.setRange(0, 100_000)
        self._xline_min.setValue(g.xline_min)
        form.addRow("Xline min:", self._xline_min)

        self._xline_max = QSpinBox()
        self._xline_max.setRange(0, 100_000)
        self._xline_max.setValue(g.xline_max)
        form.addRow("Xline max:", self._xline_max)

        # Read-only fields — displayed for context.
        n_samples_label = QLabel(str(g.n_samples))
        sample_rate_label = QLabel(f"{g.sample_rate_ms} ms")
        form.addRow("Samples (read-only):", n_samples_label)
        form.addRow("Sample rate (read-only):", sample_rate_label)

        outer.addLayout(form)

        button_row = QHBoxLayout()
        apply_btn = QPushButton("Apply override")
        apply_btn.clicked.connect(self._on_apply)
        reset_btn = QPushButton("Reset to original")
        reset_btn.clicked.connect(self._on_reset)
        button_row.addStretch(1)
        button_row.addWidget(reset_btn)
        button_row.addWidget(apply_btn)
        outer.addLayout(button_row)

    def _on_apply(self) -> None:
        new_inline_min = self._inline_min.value()
        new_inline_max = self._inline_max.value()
        new_xline_min = self._xline_min.value()
        new_xline_max = self._xline_max.value()
        if new_inline_max < new_inline_min or new_xline_max < new_xline_min:
            return  # silently no-op on invalid input; could add status hint later
        # Preserve the original count by adjusting the step so that
        # (max - min) / step + 1 == n_*. Falls back to the original step
        # when there's a single line on that axis (no step inferable).
        n_inlines = self._original.n_inlines
        n_xlines = self._original.n_xlines
        inline_step = self._original.inline_step
        xline_step = self._original.xline_step
        if n_inlines > 1:
            inline_step = max(1, (new_inline_max - new_inline_min) // (n_inlines - 1))
        if n_xlines > 1:
            xline_step = max(1, (new_xline_max - new_xline_min) // (n_xlines - 1))
        new_geom = _dc_replace(
            self._original,
            inline_min=new_inline_min,
            inline_max=new_inline_max,
            inline_step=inline_step,
            xline_min=new_xline_min,
            xline_max=new_xline_max,
            xline_step=xline_step,
        )
        self.geometryOverridden.emit(new_geom)

    def _on_reset(self) -> None:
        self._inline_min.setValue(self._original.inline_min)
        self._inline_max.setValue(self._original.inline_max)
        self._xline_min.setValue(self._original.xline_min)
        self._xline_max.setValue(self._original.xline_max)
        self.geometryReset.emit()
