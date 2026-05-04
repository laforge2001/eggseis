"""Well — log curves + deviation survey + markers, persisted as HDF5.

Storage layout (M7 step 0 spike): each well is one HDF5 file at
`<project>/wells/<name>.h5`. The file contains:
  - /deviation       — (n_md, 3) float32 array (md, x, y)
  - /logs/<name>     — (n_md,) float32 per log curve
  - /markers         — JSON-encoded list of (name, md) tuples (HDF5 string attr)
  - /surface_xy      — (2,) float64 attribute (well-head in survey coords)
  - /name            — attribute
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


class LasImportError(ValueError):
    """LAS file could not be imported. Wraps lasio errors with context."""


@dataclass
class Well:
    name: str
    deviation: np.ndarray                # (n_md, 3) float32: md, x, y
    logs: dict[str, np.ndarray] = field(default_factory=dict)
    markers: list[tuple[str, float]] = field(default_factory=list)
    surface_xy: tuple[float, float] = (0.0, 0.0)
    domain: str = "time_ms"              # "time_ms" or "depth"; intersect_section
                                         # treats md column as time-ms when "time_ms".
                                         # depth-domain wells need TWT conversion (v1.1).

    def save(self, path: str | Path) -> None:
        import h5py

        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(target, "w") as f:
            f.attrs["name"] = self.name
            f.attrs["surface_xy"] = np.asarray(self.surface_xy, dtype=np.float64)
            f.attrs["markers"] = json.dumps(list(self.markers))
            f.create_dataset("deviation", data=self.deviation.astype(np.float32))
            grp = f.create_group("logs")
            for log_name, values in self.logs.items():
                grp.create_dataset(log_name, data=np.asarray(values, dtype=np.float32))

    def intersect_section(
        self,
        axis: str,
        index: int,
        geometry,
        slab: int = 1,
    ) -> np.ndarray:
        """Return (n_points, 2) array of (x_pixel, y_pixel) where the well
        crosses the section.

        Currently only `domain == "time_ms"` is supported — the deviation
        md column is treated as time in ms and converted to sample index.
        Depth-domain wells raise ValueError until TWT conversion lands (v1.1).
        """
        if self.domain != "time_ms":
            raise ValueError(
                f"Well {self.name!r} domain={self.domain!r} not supported; "
                "only 'time_ms' wells render today (depth needs TWT conversion, v1.1)"
            )
        deviation_x = self.deviation[:, 1] + self.surface_xy[0]  # xline coord
        deviation_y = self.deviation[:, 2] + self.surface_xy[1]  # inline coord
        md = self.deviation[:, 0]
        sample_rate = geometry.sample_rate_ms

        if axis == "inline":
            # Keep points whose inline coord is within `slab` of `index`.
            mask = np.abs(deviation_y - index) <= slab
            if not mask.any():
                return np.empty((0, 2), dtype=np.float32)
            x_pix = (deviation_x[mask] - geometry.xline_min) // geometry.xline_step
            y_pix = md[mask] / sample_rate
        elif axis == "xline":
            mask = np.abs(deviation_x - index) <= slab
            if not mask.any():
                return np.empty((0, 2), dtype=np.float32)
            x_pix = (deviation_y[mask] - geometry.inline_min) // geometry.inline_step
            y_pix = md[mask] / sample_rate
        else:
            return np.empty((0, 2), dtype=np.float32)

        return np.column_stack([x_pix, y_pix]).astype(np.float32)

    @classmethod
    def load(cls, path: str | Path) -> Well:
        import h5py

        with h5py.File(Path(path), "r") as f:
            name = f.attrs["name"]
            if isinstance(name, bytes):
                name = name.decode()
            sxy = f.attrs["surface_xy"]
            markers_raw = f.attrs.get("markers", "[]")
            if isinstance(markers_raw, bytes):
                markers_raw = markers_raw.decode()
            markers = [(m[0], float(m[1])) for m in json.loads(markers_raw)]
            deviation = np.asarray(f["deviation"][:], dtype=np.float32)
            logs = {
                k: np.asarray(f["logs"][k][:], dtype=np.float32)
                for k in f["logs"].keys()
            }
        return cls(
            name=str(name),
            deviation=deviation,
            logs=logs,
            markers=markers,
            surface_xy=(float(sxy[0]), float(sxy[1])),
        )


def import_las(
    path: str | Path,
    *,
    name: str,
    surface_xy: tuple[float, float] = (0.0, 0.0),
) -> Well:
    """Import a LAS 2.0/3.0 well-log file via lasio.

    Each curve under the LAS `~ASCII` section becomes a `logs[name]` entry
    keyed by curve mnemonic. The `DEPT` (or `MD`) curve is stripped from
    `logs` and used as the MD axis of a vertical-well deviation survey
    (x = y = 0). Real deviated wells need a separate XYZ deviation file —
    use `Well(deviation=...)` directly for those.

    LAS NULL values are converted to NaN. The returned Well's `domain`
    is `"time_ms"` — the importer assumes the LAS depth axis is time in
    milliseconds. For depth-domain LAS files the result will plot at the
    wrong y-position; convert to TWT before import (v1.1 will handle this
    in-app).

    Tolerant of common malformations:
    - DEPT / MD / DEPTH / TVD as the depth axis (case-insensitive,
      whitespace-stripped).
    - NULL value sniffed from the ~Well block; defaults to -999.25 if absent.
    - NULL detection uses np.isclose so precision-drifted values still
      convert to NaN.

    Raises LasImportError(path, original_exc) on parse failure.
    """
    import lasio

    p = Path(path)
    try:
        las = lasio.read(str(p))
    except Exception as exc:
        raise LasImportError(f"{p}: {exc!r}") from exc

    # Find the depth curve, case-insensitive + whitespace-stripped.
    depth_aliases = {"DEPT", "MD", "DEPTH", "TVD"}
    md_curve = None
    for curve in las.curves:
        mnem = (curve.mnemonic or "").strip().upper()
        if mnem in depth_aliases:
            md_curve = curve.mnemonic
            break
    if md_curve is None:
        raise LasImportError(
            f"{p}: no depth curve found (looked for DEPT, MD, DEPTH, TVD)"
        )

    md = np.asarray(las[md_curve], dtype=np.float32)
    null = -999.25
    try:
        if "NULL" in las.well:
            null = float(las.well["NULL"].value)
    except (KeyError, TypeError, ValueError):
        pass

    logs: dict[str, np.ndarray] = {}
    for curve in las.curves:
        if curve.mnemonic == md_curve:
            continue
        try:
            values = np.asarray(las[curve.mnemonic], dtype=np.float32)
        except Exception:
            continue  # tolerate unreadable curves
        # Use isclose so precision-drifted NULL values still become NaN.
        values = np.where(np.isclose(values, null, atol=1e-3), np.nan, values)
        # Strip any leading/trailing whitespace from the mnemonic key.
        key = (curve.mnemonic or "").strip()
        if key:
            logs[key] = values

    deviation = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    return Well(name=name, deviation=deviation, logs=logs, surface_xy=surface_xy)
