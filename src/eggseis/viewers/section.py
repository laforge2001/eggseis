"""Section viewer: pyqtgraph ImageItem + percentile-stretched display."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from eggseis.colormaps import get_lut
from eggseis.data import SeismicVolume

DEFAULT_LUT = "gray"


class SectionViewer(QWidget):
    cursorMoved = Signal(str)

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
        self._array: np.ndarray | None = None

        self._proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
        )

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
        self._array = arr
        p_low, p_high = np.percentile(arr, [1, 99])
        if p_high == p_low:
            p_high = p_low + 1.0
        self._image.setImage(arr, levels=(float(p_low), float(p_high)))

    def _on_mouse_moved(self, evt) -> None:
        if self._volume is None or self._array is None:
            return
        scene_pos = evt[0]
        view_box = self._plot.getPlotItem().vb
        if view_box is None or not self._plot.sceneBoundingRect().contains(scene_pos):
            return
        view_pt = view_box.mapSceneToView(scene_pos)
        x = round(view_pt.x())
        y = round(view_pt.y())

        h, w = self._array.shape
        if not (0 <= x < w and 0 <= y < h):
            return

        g = self._volume.geometry
        amp = float(self._array[y, x])

        if self._axis == "inline":
            xl = g.xline_min + x * g.xline_step
            t_ms = y * g.sample_rate_ms
            text = f"Inline {self._index}  Xline {xl}  Time {t_ms:.1f} ms  Amp {amp:.4g}"
        elif self._axis == "xline":
            il = g.inline_min + x * g.inline_step
            t_ms = y * g.sample_rate_ms
            text = f"Xline {self._index}  Inline {il}  Time {t_ms:.1f} ms  Amp {amp:.4g}"
        else:
            il = g.inline_min + y * g.inline_step
            xl = g.xline_min + x * g.xline_step
            t_ms = self._index * g.sample_rate_ms
            text = f"Time {t_ms:.1f} ms  Inline {il}  Xline {xl}  Amp {amp:.4g}"

        self.cursorMoved.emit(text)
