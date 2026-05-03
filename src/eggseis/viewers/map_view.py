"""Map view: top-down 2D plan of the active survey + current slice indicator."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from eggseis.axes import Axis
from eggseis.data import SeismicVolume


class MapViewWidget(QWidget):
    """Plan view: rectangle = survey footprint, line/dot = current slice.

    Click-to-navigate emits sliceRequested(axis, index).
    """

    sliceRequested = Signal(str, int)  # ("inline" | "xline", index)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("left", "Inline")
        self._plot.setLabel("bottom", "Xline")
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        layout.addWidget(self._plot)

        self._volume: SeismicVolume | None = None
        self._outline = pg.PlotDataItem(pen=pg.mkPen("#888888", width=1.5))
        self._slice_indicator = pg.PlotDataItem(pen=pg.mkPen("#ff3333", width=2))
        self._plot.addItem(self._outline)
        self._plot.addItem(self._slice_indicator)

        self._axis: Axis = Axis.INLINE
        self._index: int = 0
        self._plot.scene().sigMouseClicked.connect(self._on_mouse_click)

    def set_volume(self, volume: SeismicVolume) -> None:
        self._volume = volume
        g = volume.geometry
        # Outline: rectangle at (xline, inline) corners.
        x = [
            g.xline_min,
            g.xline_min + g.n_xlines * g.xline_step,
            g.xline_min + g.n_xlines * g.xline_step,
            g.xline_min,
            g.xline_min,
        ]
        y = [
            g.inline_min,
            g.inline_min,
            g.inline_min + g.n_inlines * g.inline_step,
            g.inline_min + g.n_inlines * g.inline_step,
            g.inline_min,
        ]
        self._outline.setData(x=x, y=y)
        self._refresh_indicator()

    def show_slice(self, axis, index: int) -> None:
        self._axis = Axis(axis)
        self._index = index
        self._refresh_indicator()

    def _refresh_indicator(self) -> None:
        if self._volume is None:
            self._slice_indicator.setData(x=[], y=[])
            return
        g = self._volume.geometry
        if self._axis is Axis.INLINE:
            # Horizontal line at inline=index spanning xline range.
            self._slice_indicator.setData(
                x=[g.xline_min, g.xline_min + g.n_xlines * g.xline_step],
                y=[self._index, self._index],
            )
        elif self._axis is Axis.XLINE:
            self._slice_indicator.setData(
                x=[self._index, self._index],
                y=[g.inline_min, g.inline_min + g.n_inlines * g.inline_step],
            )
        else:
            # Timeslice — no x/y position to highlight; clear.
            self._slice_indicator.setData(x=[], y=[])

    def _on_mouse_click(self, evt) -> None:
        if self._volume is None or not evt.double():
            return
        # Click-to-nav on double-click. Translate scene point → data coords.
        pos = evt.scenePos()
        vb = self._plot.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(pos):
            return
        data_pt = vb.mapSceneToView(pos)
        x_xline = round(data_pt.x())
        y_inline = round(data_pt.y())
        # Decide which axis to step based on current axis.
        if self._axis is Axis.INLINE:
            self.sliceRequested.emit("inline", int(y_inline))
        elif self._axis is Axis.XLINE:
            self.sliceRequested.emit("xline", int(x_xline))
