"""Domain model for seismic data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from eggseis.axes import Axis


@dataclass(frozen=True)
class SurveyGeometry:
    """Geometric description of a 3D seismic survey."""

    inline_min: int
    inline_max: int
    inline_step: int
    xline_min: int
    xline_max: int
    xline_step: int
    n_samples: int
    sample_rate_ms: float

    @property
    def n_inlines(self) -> int:
        return (self.inline_max - self.inline_min) // self.inline_step + 1

    @property
    def n_xlines(self) -> int:
        return (self.xline_max - self.xline_min) // self.xline_step + 1

    @property
    def shape(self) -> tuple[int, int, int]:
        """(n_inlines, n_xlines, n_samples)."""
        return (self.n_inlines, self.n_xlines, self.n_samples)

    @property
    def time_max_ms(self) -> float:
        return (self.n_samples - 1) * self.sample_rate_ms

    def inline_at(self, idx: int) -> int:
        return self.inline_min + idx * self.inline_step

    def xline_at(self, idx: int) -> int:
        return self.xline_min + idx * self.xline_step

    def time_at(self, sample: int) -> float:
        return sample * self.sample_rate_ms

    def range_for(self, axis: Axis | str) -> tuple[int, int, int]:
        """Return (lo, hi, step) for the given axis, suitable for spinbox bounds."""
        axis = Axis(axis)
        if axis is Axis.INLINE:
            return self.inline_min, self.inline_max, self.inline_step
        if axis is Axis.XLINE:
            return self.xline_min, self.xline_max, self.xline_step
        return 0, self.n_samples - 1, 1


@runtime_checkable
class SeismicBackend(Protocol):
    """Storage backend interface — what every backend must implement."""

    @property
    def geometry(self) -> SurveyGeometry: ...

    @property
    def dtype(self) -> np.dtype: ...

    def read_inline(self, inline: int) -> np.ndarray: ...
    def read_xline(self, xline: int) -> np.ndarray: ...
    def read_timeslice(self, sample_index: int) -> np.ndarray: ...
    def read_trace(self, inline: int, xline: int) -> np.ndarray: ...

    @property
    def version(self) -> tuple: ...


class SeismicVolume:
    """Stable public abstraction for a 3D seismic volume.

    Plugins, viewers, and CLI commands talk to this — never to backends
    directly. Swapping the backend (MDIO, OpenVDS, TileDB) leaves the
    upstream code untouched.
    """

    def __init__(self, backend: SeismicBackend, name: str = "unnamed"):
        self._backend = backend
        self.name = name

    @property
    def geometry(self) -> SurveyGeometry:
        return self._backend.geometry

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.geometry.shape

    @property
    def dtype(self) -> np.dtype:
        return self._backend.dtype

    @property
    def version(self) -> tuple:
        """Opaque tuple uniquely identifying this volume's bytes (cache key input)."""
        return self._backend.version

    def read_inline(self, inline: int) -> np.ndarray:
        """Read single inline as shape (n_xlines, n_samples)."""
        return self._backend.read_inline(inline)

    def read_xline(self, xline: int) -> np.ndarray:
        """Read single crossline as shape (n_inlines, n_samples)."""
        return self._backend.read_xline(xline)

    def read_timeslice(self, sample_index: int) -> np.ndarray:
        """Read single time slice as shape (n_inlines, n_xlines)."""
        return self._backend.read_timeslice(sample_index)

    def read_trace(self, inline: int, xline: int) -> np.ndarray:
        """Read single trace as shape (n_samples,)."""
        return self._backend.read_trace(inline, xline)

    def __repr__(self) -> str:
        g = self.geometry
        return (
            f"SeismicVolume(name={self.name!r}, "
            f"shape={g.shape}, dtype={self.dtype}, "
            f"sample_rate={g.sample_rate_ms}ms)"
        )
