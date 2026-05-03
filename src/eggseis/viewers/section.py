"""Section viewer: pyqtgraph ImageItem + percentile-stretched display."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from eggseis.axes import Axis
from eggseis.colormaps import get_lut
from eggseis.data import SeismicVolume
from eggseis.data.horizon import Horizon
from eggseis.data.well import Well
from eggseis.viewers.horizon_overlay import (
    inline_polyline_points,
    xline_polyline_points,
)

DEFAULT_LUT = "gray"
_MOUSE_RATE_HZ = 60
_PERCENTILE_SUBSAMPLE = 8  # stride into raveled slice when estimating 1/99 percentiles


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
        self._vb = self._plot.getPlotItem().vb
        layout.addWidget(self._plot)

        # Transient warning banner for "horizon not visible" / similar UX hints.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "QLabel { color: #aa6600; padding: 2px 6px; font-size: 11px; }"
        )
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._volume: SeismicVolume | None = None
        self._lut_name = DEFAULT_LUT
        self._image.setLookupTable(get_lut(self._lut_name))
        self._axis: Axis = Axis.INLINE
        self._index: int = 0
        self._last_emit_key: tuple | None = None
        self._overlay: np.ndarray | None = None
        self._partial_overlay: bool = False
        # Baseline levels = (p1, p99) of the raw slice. When locked, overlays
        # render against this fixed range so amplitude-changing plugins (gain,
        # clip) are visibly intuitive instead of being normalized away.
        self._baseline_levels: tuple[float, float] | None = None
        self._levels_locked: bool = True

        self._proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved,
            rateLimit=_MOUSE_RATE_HZ,
            slot=self._on_mouse_moved,
        )

        # Horizon overlays keyed by horizon name; values hold both the
        # Horizon model and the pyqtgraph plot item so we can re-render
        # the polyline on every slice change without re-adding the item.
        self._horizon_overlays: dict[str, tuple[Horizon, pg.PlotDataItem]] = {}
        self._well_overlays: dict[str, tuple[Well, pg.PlotDataItem]] = {}

    @property
    def current_axis(self) -> str:
        return self._axis.value

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def lut_name(self) -> str:
        return self._lut_name

    @property
    def has_volume(self) -> bool:
        return self._volume is not None

    @property
    def volume(self) -> SeismicVolume | None:
        return self._volume

    @property
    def has_overlay(self) -> bool:
        return self._overlay is not None

    @property
    def levels_locked(self) -> bool:
        return self._levels_locked

    def set_levels_locked(self, locked: bool) -> None:
        """When True, overlay paints reuse the raw-slice percentile levels."""
        self._levels_locked = locked
        self._render()

    def set_overlay(self, arr: np.ndarray, *, partial: bool = False) -> None:
        """Display `arr` instead of raw data.

        `partial=True` indicates an in-progress paint from a tile worker;
        suppresses any baseline-level recompute so the colour scale stays
        stable across the run. The orchestrator's final `sectionReady` paint
        passes `partial=False` to allow level refresh when levels are not
        locked.
        """
        self._overlay = arr
        self._partial_overlay = partial
        self._render()

    def clear_overlay(self) -> None:
        self._overlay = None
        self._partial_overlay = False
        self._render()

    @property
    def geometry(self):
        return self._volume.geometry if self._volume else None

    def set_volume(self, volume: SeismicVolume) -> None:
        self._volume = volume
        self._axis = Axis.INLINE
        self._index = volume.geometry.inline_min
        self._last_emit_key = None
        self._overlay = None
        self._partial_overlay = False
        self._baseline_levels = None
        self._render()

    def show_slice(self, axis: Axis | str, index: int) -> None:
        self._axis = Axis(axis)
        self._index = index
        self._last_emit_key = None
        # Slice changed → overlay + baseline both stale.
        self._overlay = None
        self._partial_overlay = False
        self._baseline_levels = None
        self._render()
        self._refresh_horizons()
        self._refresh_wells()

    # --- horizon overlays --------------------------------------------------

    def add_horizon_overlay(self, horizon: Horizon) -> None:
        item = pg.PlotDataItem(pen=pg.mkPen(horizon.color, width=2))
        self._plot.addItem(item)
        self._horizon_overlays[horizon.name] = (horizon, item)
        self._refresh_horizons()

    def remove_horizon_overlay(self, name: str) -> None:
        entry = self._horizon_overlays.pop(name, None)
        if entry is not None:
            _, item = entry
            self._plot.removeItem(item)

    def horizon_count(self) -> int:
        return len(self._horizon_overlays)

    def horizon_overlay_names(self) -> list[str]:
        return list(self._horizon_overlays.keys())

    # --- well overlays ----------------------------------------------------

    def add_well_overlay(self, well: Well, *, color: str = "#3399ff") -> None:
        item = pg.PlotDataItem(pen=pg.mkPen(color, width=2), symbol="o", symbolSize=4)
        self._plot.addItem(item)
        self._well_overlays[well.name] = (well, item)
        self._refresh_wells()

    def remove_well_overlay(self, name: str) -> None:
        entry = self._well_overlays.pop(name, None)
        if entry is not None:
            _, item = entry
            self._plot.removeItem(item)

    def well_count(self) -> int:
        return len(self._well_overlays)

    def _refresh_wells(self) -> None:
        if self._volume is None:
            return
        geom = self._volume.geometry
        for well, item in self._well_overlays.values():
            pts = well.intersect_section(self._axis.value, self._index, geom)
            if pts.size:
                item.setData(x=pts[:, 0], y=pts[:, 1])
            else:
                item.setData(x=[], y=[])

    def _refresh_horizons(self) -> None:
        if self._volume is None:
            return
        geom = self._volume.geometry
        for horizon, item in self._horizon_overlays.values():
            if self._axis is Axis.INLINE:
                pts = inline_polyline_points(horizon, geom, self._index)
            elif self._axis is Axis.XLINE:
                pts = xline_polyline_points(horizon, geom, self._index)
            else:
                # Timeslice: no polyline (would need a contour). Hide.
                item.setData(x=[], y=[])
                continue
            if pts.size:
                item.setData(x=pts[:, 0], y=pts[:, 1])
            else:
                item.setData(x=[], y=[])

    def set_colormap(self, name: str) -> None:
        self._lut_name = name
        self._image.setLookupTable(get_lut(name))

    # --- transient warning banner ----------------------------------------

    def show_warning(self, text: str) -> None:
        if not text:
            self._status_label.setVisible(False)
            return
        self._status_label.setText(text)
        self._status_label.setVisible(True)

    def clear_warning(self) -> None:
        self._status_label.setVisible(False)
        self._status_label.setText("")

    def _render(self) -> None:
        if self._volume is None:
            return

        showing_overlay = self._overlay is not None
        if showing_overlay:
            source = self._overlay
        elif self._axis is Axis.INLINE:
            source = self._volume.read_inline(self._index)
        elif self._axis is Axis.XLINE:
            source = self._volume.read_xline(self._index)
        else:
            source = self._volume.read_timeslice(self._index)

        # Inline / xline: time on vertical axis (transpose).
        # Timeslice: already (n_inlines, n_xlines).
        arr = source.T if self._axis in (Axis.INLINE, Axis.XLINE) else source

        # Reuse baseline levels when locked, OR when painting an in-progress
        # tile (partial=True) so the colour scale stays stable across the run.
        if (
            showing_overlay
            and self._baseline_levels is not None
            and (self._levels_locked or self._partial_overlay)
        ):
            levels = self._baseline_levels
        else:
            levels = self._compute_levels(arr)
            if not showing_overlay:
                # Cache raw-slice levels so overlay paints can lock to them.
                self._baseline_levels = levels

        self._image.setImage(arr, levels=levels)

    @staticmethod
    def _compute_levels(arr: np.ndarray) -> tuple[float, float]:
        sample = arr.ravel()[::_PERCENTILE_SUBSAMPLE]
        p_low, p_high = np.percentile(sample, [1, 99])
        if p_high == p_low:
            p_high = p_low + 1.0
        return float(p_low), float(p_high)

    def _on_mouse_moved(self, evt) -> None:
        if self._volume is None:
            return
        arr = self._image.image
        if arr is None:
            return
        scene_pos = evt[0]
        view_pt = self._vb.mapSceneToView(scene_pos)
        x = round(view_pt.x())
        y = round(view_pt.y())

        h, w = arr.shape
        if not (0 <= x < w and 0 <= y < h):
            return

        key = (self._axis, self._index, x, y)
        if key == self._last_emit_key:
            return
        self._last_emit_key = key

        g = self._volume.geometry
        amp = float(arr[y, x])

        if self._axis is Axis.INLINE:
            text = (
                f"Inline {self._index}  Xline {g.xline_at(x)}  "
                f"Time {g.time_at(y):.1f} ms  Amp {amp:.4g}"
            )
        elif self._axis is Axis.XLINE:
            text = (
                f"Xline {self._index}  Inline {g.inline_at(x)}  "
                f"Time {g.time_at(y):.1f} ms  Amp {amp:.4g}"
            )
        else:
            text = (
                f"Time {g.time_at(self._index):.1f} ms  "
                f"Inline {g.inline_at(y)}  Xline {g.xline_at(x)}  Amp {amp:.4g}"
            )

        self.cursorMoved.emit(text)
