"""Horizon — gridded 2D surface stored as Zarr + JSON sidecar.

Storage layout (M7 step 0 spike): each horizon is a directory under
`<project>/horizons/<name>/` containing:
  - `horizon` — Zarr array, shape `(n_inlines, n_xlines)`, dtype float32, ms.
  - `sidecar.json` — non-gridded metadata (color, picker, geometry_ref).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr

DEFAULT_COLOR = "#ffcc00"


@dataclass
class Horizon:
    name: str
    grid: np.ndarray              # (n_inlines, n_xlines) float32, ms
    geometry_ref: str             # relative path back to source survey
    color: str = DEFAULT_COLOR
    picker: str = ""
    unit: str = "ms"
    inline_min: int = 0
    xline_min: int = 0
    inline_step: int = 1
    xline_step: int = 1

    def save(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        store = zarr.open(str(target / "horizon"), mode="w")
        # zarr.open returns a Group when path is a directory; create the array.
        if hasattr(store, "create_array"):
            arr = store.create_array(
                name="data", shape=self.grid.shape, dtype=self.grid.dtype
            )
            arr[:] = self.grid
        else:
            store[:] = self.grid

        sidecar = {
            "name": self.name,
            "geometry_ref": self.geometry_ref,
            "color": self.color,
            "picker": self.picker,
            "unit": self.unit,
            "inline_min": self.inline_min,
            "xline_min": self.xline_min,
            "inline_step": self.inline_step,
            "xline_step": self.xline_step,
        }
        (target / "sidecar.json").write_text(json.dumps(sidecar, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> Horizon:
        target = Path(path).expanduser()
        sidecar = json.loads((target / "sidecar.json").read_text())

        store = zarr.open(str(target / "horizon"), mode="r")
        if hasattr(store, "keys"):
            grid = store["data"][:]
        else:
            grid = store[:]

        return cls(
            name=sidecar["name"],
            grid=np.asarray(grid, dtype=np.float32),
            geometry_ref=sidecar["geometry_ref"],
            color=sidecar.get("color", DEFAULT_COLOR),
            picker=sidecar.get("picker", ""),
            unit=sidecar.get("unit", "ms"),
            inline_min=sidecar.get("inline_min", 0),
            xline_min=sidecar.get("xline_min", 0),
            inline_step=sidecar.get("inline_step", 1),
            xline_step=sidecar.get("xline_step", 1),
        )

    def value_at(self, inline: int, xline: int) -> float | None:
        """Look up the horizon value at a survey-coord (inline, xline) pair.

        Returns None for out-of-bounds OR NaN cells (unknown samples).
        """
        i = (inline - self.inline_min) // self.inline_step
        j = (xline - self.xline_min) // self.xline_step
        if not (0 <= i < self.grid.shape[0] and 0 <= j < self.grid.shape[1]):
            return None
        v = float(self.grid[i, j])
        if np.isnan(v):
            return None
        return v


def import_opendtect_ascii(
    path: str | Path,
    *,
    name: str,
    inline_min: int,
    n_inlines: int,
    inline_step: int,
    xline_min: int,
    n_xlines: int,
    xline_step: int,
    geometry_ref: str,
    color: str = DEFAULT_COLOR,
) -> Horizon:
    """Import an OpendTect ASCII horizon export.

    Comment lines starting with `#` or `"` are skipped; blank lines too.
    Data columns are whitespace-separated. Auto-detects column count:
      - 5 cols: inline xline X Y time (drops X, Y)
      - 3 cols: inline xline time
    Other column counts raise ValueError.
    """
    grid = np.full((n_inlines, n_xlines), np.nan, dtype=np.float32)
    with Path(path).open() as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith('"'):
                continue
            parts = line.split()
            if len(parts) == 5:
                inline = int(parts[0])
                xline = int(parts[1])
                time = float(parts[4])
            elif len(parts) == 3:
                inline = int(parts[0])
                xline = int(parts[1])
                time = float(parts[2])
            else:
                raise ValueError(
                    f"OpendTect ASCII: expected 3 or 5 columns, got {len(parts)} "
                    f"on line {raw!r}"
                )
            i = (inline - inline_min) // inline_step
            j = (xline - xline_min) // xline_step
            if not (0 <= i < n_inlines and 0 <= j < n_xlines):
                continue
            grid[i, j] = time
    return Horizon(
        name=name,
        grid=grid,
        geometry_ref=geometry_ref,
        color=color,
        inline_min=inline_min,
        xline_min=xline_min,
        inline_step=inline_step,
        xline_step=xline_step,
    )


def import_xyz_csv_autodetect(
    path: str | Path,
    *,
    name: str,
    geometry_ref: str,
    color: str = DEFAULT_COLOR,
) -> Horizon:
    """Import an XYZ CSV without a known survey geometry.

    Auto-detects inline_min/max and xline_min/max from the CSV's data;
    inline_step and xline_step assumed 1 (the common case for CSV exports).
    Useful for project-only horizon import before a compatible survey is opened.
    """
    rows = []
    with Path(path).open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((int(row["inline"]), int(row["xline"]), float(row["time"])))
    if not rows:
        raise ValueError(f"CSV {path} has no data rows")
    inlines = [r[0] for r in rows]
    xlines = [r[1] for r in rows]
    inline_min, inline_max = min(inlines), max(inlines)
    xline_min, xline_max = min(xlines), max(xlines)
    n_inlines = inline_max - inline_min + 1
    n_xlines = xline_max - xline_min + 1
    grid = np.full((n_inlines, n_xlines), np.nan, dtype=np.float32)
    for inline, xline, time in rows:
        grid[inline - inline_min, xline - xline_min] = time
    return Horizon(
        name=name,
        grid=grid,
        geometry_ref=geometry_ref,
        color=color,
        inline_min=inline_min,
        xline_min=xline_min,
        inline_step=1,
        xline_step=1,
    )


def import_xyz_csv(
    path: str | Path,
    *,
    name: str,
    inline_min: int,
    n_inlines: int,
    inline_step: int,
    xline_min: int,
    n_xlines: int,
    xline_step: int,
    geometry_ref: str,
    color: str = DEFAULT_COLOR,
) -> Horizon:
    """Import a 3-column inline/xline/time CSV into a Horizon.

    Samples outside the survey geometry are silently dropped. Cells with
    no sample in the CSV remain NaN.
    """
    grid = np.full((n_inlines, n_xlines), np.nan, dtype=np.float32)
    with Path(path).open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            inline = int(row["inline"])
            xline = int(row["xline"])
            time = float(row["time"])
            i = (inline - inline_min) // inline_step
            j = (xline - xline_min) // xline_step
            if not (0 <= i < n_inlines and 0 <= j < n_xlines):
                continue
            grid[i, j] = time
    return Horizon(
        name=name,
        grid=grid,
        geometry_ref=geometry_ref,
        color=color,
        inline_min=inline_min,
        xline_min=xline_min,
        inline_step=inline_step,
        xline_step=xline_step,
    )
