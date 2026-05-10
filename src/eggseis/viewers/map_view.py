"""Map view: top-down 2D plan of the active survey + current slice indicator."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.viewers.theme import apply_to_plot_widget
from eggseis.viewers.theme import colors as _theme_colors

_WELL_MARKER_SIZE = 12
_WELL_SNAP_RADIUS = 5.0


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
        apply_to_plot_widget(self._plot)
        self._plot.setLabel("left", "Inline")
        self._plot.setLabel("bottom", "Xline")
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        layout.addWidget(self._plot)

        self._volume: SeismicVolume | None = None
        c = _theme_colors()
        self._outline = pg.PlotDataItem(pen=pg.mkPen(c["axis"], width=1.5))
        self._slice_indicator = pg.PlotDataItem(
            pen=pg.mkPen(c["slice_indicator"], width=2)
        )
        self._plot.addItem(self._outline)
        self._plot.addItem(self._slice_indicator)

        self._axis: Axis = Axis.INLINE
        self._index: int = 0
        # Per-well scatter items keyed by well name, plus surface_xy lookup
        # for click-to-navigate hit testing.
        self._well_marker_items: dict[str, pg.ScatterPlotItem] = {}
        self._well_positions: dict[str, tuple[float, float]] = {}
        self._plot.scene().sigMouseClicked.connect(self._on_mouse_click)

    def set_volume(self, volume: SeismicVolume) -> None:
        # Switching surveys wipes well state from the viewer — clear markers
        # so we don't leave stale dots from the previous volume.
        self.clear_well_markers()
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

    def add_well_marker(self, name: str, surface_xy: tuple[float, float]) -> None:
        """Drop or replace a dot at the well's surface_xy on the plan view."""
        pos = (float(surface_xy[0]), float(surface_xy[1]))
        if self._well_positions.get(name) == pos:
            return
        color = _theme_colors()["well_marker"]
        item = pg.ScatterPlotItem(
            x=[pos[0]],
            y=[pos[1]],
            size=_WELL_MARKER_SIZE,
            symbol="o",
            brush=color,
            pen=pg.mkPen(color, width=1.5),
        )
        prev = self._well_marker_items.pop(name, None)
        if prev is not None:
            self._plot.removeItem(prev)
        self._plot.addItem(item)
        self._well_marker_items[name] = item
        self._well_positions[name] = pos

    def remove_well_marker(self, name: str) -> None:
        item = self._well_marker_items.pop(name, None)
        if item is not None:
            self._plot.removeItem(item)
        self._well_positions.pop(name, None)

    def clear_well_markers(self) -> None:
        for name in list(self._well_marker_items.keys()):
            self.remove_well_marker(name)

    def _on_mouse_click(self, evt) -> None:
        if self._volume is None or not evt.double():
            return
        # Click-to-nav on double-click. Translate scene point → data coords.
        pos = evt.scenePos()
        vb = self._plot.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(pos):
            return
        data_pt = vb.mapSceneToView(pos)
        click_xline = data_pt.x()
        click_inline = data_pt.y()
        nearest_name = None
        nearest_dist = float("inf")
        for name, (xl, il) in self._well_positions.items():
            d = ((xl - click_xline) ** 2 + (il - click_inline) ** 2) ** 0.5
            if d < nearest_dist:
                nearest_dist = d
                nearest_name = name
        if nearest_name is not None and nearest_dist < _WELL_SNAP_RADIUS:
            _wxl, wil = self._well_positions[nearest_name]
            self.sliceRequested.emit("inline", round(wil))
            return
        # Fallback: existing behavior — snap to integer grid, drive section
        # axis from the current map axis.
        x_xline = round(click_xline)
        y_inline = round(click_inline)
        if self._axis is Axis.INLINE:
            self.sliceRequested.emit("inline", int(y_inline))
        elif self._axis is Axis.XLINE:
            self.sliceRequested.emit("xline", int(x_xline))
