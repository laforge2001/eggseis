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


@dataclass
class Well:
    name: str
    deviation: np.ndarray                # (n_md, 3) float32: md, x, y
    logs: dict[str, np.ndarray] = field(default_factory=dict)
    markers: list[tuple[str, float]] = field(default_factory=list)
    surface_xy: tuple[float, float] = (0.0, 0.0)

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

    LAS NULL values are converted to NaN.
    """
    import lasio

    las = lasio.read(str(path))
    md_curve = None
    for candidate in ("DEPT", "MD", "DEPTH"):
        if candidate in las.curves:
            md_curve = candidate
            break
    if md_curve is None:
        raise ValueError(
            f"LAS file {path} has no DEPT / MD / DEPTH curve — cannot infer MD axis"
        )

    md = np.asarray(las[md_curve], dtype=np.float32)
    null = float(las.well["NULL"].value) if "NULL" in las.well else -999.25
    logs: dict[str, np.ndarray] = {}
    for curve in las.curves:
        if curve.mnemonic == md_curve:
            continue
        values = np.asarray(las[curve.mnemonic], dtype=np.float32)
        values = np.where(values == null, np.nan, values)
        logs[curve.mnemonic] = values

    deviation = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    return Well(name=name, deviation=deviation, logs=logs, surface_xy=surface_xy)
