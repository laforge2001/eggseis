"""MDIO storage backend (mdio v1 / xarray-based)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from eggseis.data import SurveyGeometry

INLINE_DIM_CANDIDATES = ("inline",)
XLINE_DIM_CANDIDATES = ("crossline", "xline")
SAMPLE_DIM_CANDIDATES = ("time", "depth", "sample", "twt")


class MDIOBackend:
    """Read 3D seismic from an MDIO v1 store via xarray."""

    def __init__(self, path: str | Path):
        from mdio import open_mdio

        self.path = Path(path)
        self._ds = open_mdio(str(self.path))

        self._var_name = self._resolve_data_variable()
        self._var = self._ds[self._var_name]
        self._inline_dim = self._resolve_dim(INLINE_DIM_CANDIDATES, "inline")
        self._xline_dim = self._resolve_dim(XLINE_DIM_CANDIDATES, "crossline")
        self._sample_dim = self._resolve_dim(SAMPLE_DIM_CANDIDATES, "time/depth")

        self._geometry = self._build_geometry()

    def _resolve_data_variable(self) -> str:
        default = self._ds.attrs.get("defaultVariableName")
        if default and default in self._ds.data_vars:
            return default
        candidates = [
            name
            for name, var in self._ds.data_vars.items()
            if var.ndim == 3 and np.issubdtype(var.dtype, np.floating)
        ]
        if not candidates:
            msg = f"No 3D floating-point data variable found in {self.path}"
            raise ValueError(msg)
        candidates.sort(key=lambda n: self._ds[n].size, reverse=True)
        return candidates[0]

    def _resolve_dim(self, candidates: tuple[str, ...], label: str) -> str:
        for name in candidates:
            if name in self._var.dims:
                return name
        msg = f"Could not find {label} dimension in {self._var.dims}; tried {candidates}"
        raise ValueError(msg)

    def _build_geometry(self) -> SurveyGeometry:
        inline_min, inline_max, inline_step = _coord_range(
            self._ds.coords[self._inline_dim].values
        )
        xline_min, xline_max, xline_step = _coord_range(
            self._ds.coords[self._xline_dim].values
        )
        sample_coord = self._ds.coords[self._sample_dim]
        return SurveyGeometry(
            inline_min=inline_min,
            inline_max=inline_max,
            inline_step=inline_step,
            xline_min=xline_min,
            xline_max=xline_max,
            xline_step=xline_step,
            n_samples=int(sample_coord.size),
            sample_rate_ms=_sample_rate_ms(sample_coord),
        )

    @property
    def geometry(self) -> SurveyGeometry:
        return self._geometry

    @property
    def dtype(self) -> np.dtype:
        return self._var.dtype

    @property
    def version(self) -> tuple:
        """`(backend_kind, resolved_path, st_size, st_mtime_ns)` — used as a cache key.

        For MDIO, `path` is a directory; its `st_mtime_ns` updates whenever
        immediate children change. Adequate for read-only surveys; in-place
        chunk edits at identical size + mtime would falsely hit the cache,
        and that is acceptable for v1.0.
        """
        p = self.path.resolve()
        st = p.stat()
        return ("mdio", str(p), st.st_size, st.st_mtime_ns)

    def read_inline(self, inline: int) -> np.ndarray:
        return (
            self._var.sel({self._inline_dim: inline})
            .transpose(self._xline_dim, self._sample_dim)
            .values
        )

    def read_xline(self, xline: int) -> np.ndarray:
        return (
            self._var.sel({self._xline_dim: xline})
            .transpose(self._inline_dim, self._sample_dim)
            .values
        )

    def read_timeslice(self, sample_index: int) -> np.ndarray:
        return (
            self._var.isel({self._sample_dim: sample_index})
            .transpose(self._inline_dim, self._xline_dim)
            .values
        )

    def read_trace(self, inline: int, xline: int) -> np.ndarray:
        return (
            self._var.sel({self._inline_dim: inline, self._xline_dim: xline}).values
        )


def _coord_range(coord: np.ndarray) -> tuple[int, int, int]:
    if coord.size == 0:
        msg = "Empty coordinate array"
        raise ValueError(msg)
    if coord.size == 1:
        v = int(coord[0])
        return v, v, 1
    diffs = np.diff(coord)
    if not np.all(diffs == diffs[0]):
        msg = f"Non-uniform coordinate spacing: diffs={np.unique(diffs)}"
        raise ValueError(msg)
    step = int(diffs[0])
    if step == 0:
        msg = "Coordinate has zero step"
        raise ValueError(msg)
    return int(coord[0]), int(coord[-1]), step


def _sample_rate_ms(coord) -> float:
    """Sample rate in ms, derived from coord step + units attr."""
    values = coord.values
    if values.size < 2:
        return 0.0
    step = float(values[1] - values[0])
    units = (coord.attrs.get("units") or "").lower()
    if units in ("s", "sec", "second", "seconds"):
        return step * 1000.0
    return step
