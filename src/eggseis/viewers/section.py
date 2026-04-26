"""Section viewer: pyqtgraph ImageItem + percentile-stretched display."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from eggseis.colormaps import get_lut
from eggseis.data import SeismicVolume

DEFAULT_LUT = "gray"


class SectionViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.invertY(True)
        self._image = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image)
        layout.addWidget(self._plot)

        self._volume: SeismicVolume | None = None
        self._lut_name = DEFAULT_LUT
        self._image.setLookupTable(get_lut(self._lut_name))
        self._axis: str = "inline"
        self._index: int = 0

    @property
    def current_axis(self) -> str:
        return self._axis

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def lut_name(self) -> str:
        return self._lut_name

    @property
    def has_volume(self) -> bool:
        return self._volume is not None

    def set_volume(self, volume: SeismicVolume) -> None:
        self._volume = volume
        self._axis = "inline"
        self._index = volume.geometry.inline_min
        self._render()

    def show_slice(self, axis: str, index: int) -> None:
        if axis not in ("inline", "xline", "timeslice"):
            raise ValueError(f"Unknown axis {axis!r}")
        self._axis = axis
        self._index = index
        self._render()

    def set_colormap(self, name: str) -> None:
        self._lut_name = name
        self._image.setLookupTable(get_lut(name))

    def _render(self) -> None:
        if self._volume is None:
            return
        if self._axis == "inline":
            arr = self._volume.read_inline(self._index).T
        elif self._axis == "xline":
            arr = self._volume.read_xline(self._index).T
        else:
            arr = self._volume.read_timeslice(self._index)
        p_low, p_high = np.percentile(arr, [1, 99])
        if p_high == p_low:
            p_high = p_low + 1.0
        self._image.setImage(arr, levels=(float(p_low), float(p_high)))
