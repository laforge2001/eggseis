"""M7 spike — horizon storage. Throwaway.

Tests two options for storing horizons on disk:
  A. As a 2D Zarr array sibling-of-amplitude inside the existing mdio store.
  B. As a standalone Zarr store at examples/demo-project/horizons/<name>.zarr.

For each: write, close, reopen, verify round-trip.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import xarray as xr
import zarr
from mdio import open_mdio

ROOT = Path(__file__).resolve().parents[1]
WEDGE = ROOT / "examples" / "demo-project" / "wedge.mdio"


def _make_synthetic_horizon(ds: xr.Dataset) -> np.ndarray:
    """Smooth dipping surface in time (ms), one value per (inline, xline)."""
    n_il = ds.sizes["inline"]
    n_xl = ds.sizes["crossline"]
    horizon = np.zeros((n_il, n_xl), dtype=np.float32)
    for i in range(n_il):
        for j in range(n_xl):
            horizon[i, j] = 60.0 + 1.5 * i + 0.8 * j  # ms
    return horizon


def option_a_sibling_zarr(ds: xr.Dataset, horizon: np.ndarray) -> bool:
    """Add 'horizon_top' as a 2D variable inside the same Zarr root."""
    print("\n=== Option A: side-var inside the mdio Zarr store ===")
    try:
        # Try the obvious xarray path first.
        new_ds = xr.Dataset(
            data_vars={
                "horizon_top": (("inline", "crossline"), horizon),
            },
            coords={"inline": ds.coords["inline"], "crossline": ds.coords["crossline"]},
        )
        new_ds.to_zarr(str(WEDGE), mode="a")
        print("  to_zarr mode='a' wrote new variable.")
    except Exception as exc:
        print(f"  to_zarr mode='a' FAILED: {type(exc).__name__}: {exc}")
        return False

    # Reopen the mdio store.
    try:
        rds = open_mdio(str(WEDGE))
        print(f"  reopened. data_vars now: {list(rds.data_vars)}")
        if "horizon_top" not in rds.data_vars:
            print("  horizon_top NOT visible via open_mdio")
            return False
        got = rds["horizon_top"].values
        ok = np.array_equal(got, horizon)
        print(f"  round-trip equal: {ok}")
        return ok
    except Exception as exc:
        print(f"  reopen FAILED: {type(exc).__name__}: {exc}")
        return False


def option_b_sibling_store(horizon: np.ndarray) -> bool:
    """Write horizon to a separate sibling zarr store."""
    print("\n=== Option B: standalone sibling Zarr store ===")
    horizons_dir = WEDGE.parent / "horizons"
    horizons_dir.mkdir(exist_ok=True)
    target = horizons_dir / "top.zarr"
    if target.exists():
        shutil.rmtree(target)

    try:
        store = zarr.open(str(target), mode="w")
        store.create_array(name="horizon", shape=horizon.shape, dtype=horizon.dtype)
        store["horizon"][:] = horizon
        store.attrs["unit"] = "ms"
        store.attrs["picker"] = "synthetic spike"
        store.attrs["geometry_ref"] = "../wedge.mdio"
        print(f"  wrote {target}")
    except Exception as exc:
        print(f"  write FAILED: {type(exc).__name__}: {exc}")
        return False

    # Reopen, verify.
    try:
        re = zarr.open(str(target), mode="r")
        got = re["horizon"][:]
        attrs = dict(re.attrs)
        ok = np.array_equal(got, horizon)
        print(f"  reopened, attrs: {attrs}, round-trip equal: {ok}")
        return ok
    except Exception as exc:
        print(f"  reopen FAILED: {type(exc).__name__}: {exc}")
        return False


def render_math_check(horizon: np.ndarray, ds: xr.Dataset) -> None:
    """Pretend we render: for inline=10, find xline crossings and depth."""
    print("\n=== render math check ===")
    inline_idx = 10
    xline_axis = ds.coords["crossline"].values
    horizon_at_inline = horizon[inline_idx]
    print(f"  inline {ds.coords['inline'].values[inline_idx]}: "
          f"depth ranges {horizon_at_inline.min():.1f} - {horizon_at_inline.max():.1f} ms "
          f"across {len(xline_axis)} xlines")
    # In a real overlay we'd convert these depths to image-Y pixels via
    # SurveyGeometry.time_at(...), then drop a polyline. Math is trivial;
    # the spike's job is the storage shape, not the render code.
    print("  [render math is trivial — not exercised in spike]")


def main() -> int:
    if not WEDGE.exists():
        print(f"missing fixture: {WEDGE} — run scripts/build_demo_data.py first")
        return 1

    ds = open_mdio(str(WEDGE))
    horizon = _make_synthetic_horizon(ds)
    print(f"synthetic horizon shape: {horizon.shape}")

    a_ok = option_a_sibling_zarr(ds, horizon)
    b_ok = option_b_sibling_store(horizon)
    render_math_check(horizon, ds)

    print("\n=== verdict ===")
    print(f"  Option A (mdio side-var): {'PASS' if a_ok else 'FAIL'}")
    print(f"  Option B (sibling zarr):  {'PASS' if b_ok else 'FAIL'}")

    # Bonus: sidecar JSON written alongside option B target.
    sidecar = WEDGE.parent / "horizons" / "top.json"
    sidecar.write_text(json.dumps({
        "name": "Top of test reflector",
        "color": "#ffcc00",
        "unit": "ms",
        "geometry_ref": "../wedge.mdio",
    }, indent=2))
    print(f"  sidecar JSON written: {sidecar}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
