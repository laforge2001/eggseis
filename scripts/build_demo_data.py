"""Generate synthetic MDIO surveys for the demo project.

Run this to (re)create:
  - examples/demo-project/wedge.mdio   (dipping reflectors + channel feature)
  - examples/demo-project/checkerboard.mdio (alternating amplitude pattern)

Usage:
  source .venv/bin/activate
  python scripts/build_demo_data.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import xarray as xr
from mdio import to_mdio
from scipy.ndimage import convolve1d


def _ricker(n_samples: int, dt_ms: float, f_hz: float = 30.0) -> np.ndarray:
    """Discrete Ricker wavelet centered in the window."""
    t = (np.arange(n_samples) - n_samples / 2) * (dt_ms / 1000.0)
    a = (np.pi * f_hz * t) ** 2
    return ((1.0 - 2.0 * a) * np.exp(-a)).astype(np.float32)


def _convolve_axis(reflectivity: np.ndarray, wavelet: np.ndarray) -> np.ndarray:
    """Convolve along the last (time) axis, keeping shape."""
    return convolve1d(
        reflectivity, wavelet, axis=-1, mode="constant", cval=0.0
    ).astype(np.float32)


def build_wedge(path: Path) -> None:
    """Dipping reflector + channel feature, convolved with a 30 Hz Ricker."""
    n_il, n_xl, n_t = 32, 24, 96
    dt_ms = 4.0
    inline = np.arange(100, 100 + n_il, dtype=np.int32)
    crossline = np.arange(300, 300 + n_xl, dtype=np.int32)
    time = np.arange(n_t, dtype=np.float32) * dt_ms

    refl = np.zeros((n_il, n_xl, n_t), dtype=np.float32)
    # Strong dipping reflector
    for i in range(n_il):
        for j in range(n_xl):
            depth = int(20 + 0.6 * i + 0.3 * j)
            if 0 <= depth < n_t:
                refl[i, j, depth] = 1.0
    # Second weaker reflector dipping the other way
    for i in range(n_il):
        for j in range(n_xl):
            depth = int(60 + 0.2 * (n_il - i) - 0.4 * j)
            if 0 <= depth < n_t:
                refl[i, j, depth] = -0.6
    # Channel feature: amplitude shadow centered on inline 14, xline 12
    for i in range(n_il):
        for j in range(n_xl):
            if abs(i - 14) < 3 and abs(j - 12) < 4:
                refl[i, j, 35:55] *= 0.2

    wavelet = _ricker(31, dt_ms, f_hz=28.0)
    data = _convolve_axis(refl, wavelet)
    rng = np.random.default_rng(seed=11)
    data += 0.04 * rng.standard_normal(data.shape).astype(np.float32)

    if path.exists():
        shutil.rmtree(path)
    ds = xr.Dataset(
        data_vars={"amplitude": (("inline", "crossline", "time"), data)},
        coords={"inline": inline, "crossline": crossline, "time": time},
        attrs={"defaultVariableName": "amplitude"},
    )
    ds.coords["time"].attrs["units"] = "ms"
    to_mdio(ds, str(path), mode="w")
    print(f"wrote {path} ({n_il}x{n_xl}x{n_t})")


def build_checkerboard(path: Path) -> None:
    """Alternating high/low amplitude bands — easy to see attribute behaviour."""
    n_il, n_xl, n_t = 20, 16, 80
    dt_ms = 4.0
    inline = np.arange(500, 500 + n_il, dtype=np.int32)
    crossline = np.arange(800, 800 + n_xl, dtype=np.int32)
    time = np.arange(n_t, dtype=np.float32) * dt_ms

    # Alternating amplitude per (inline-block, time-block)
    refl = np.zeros((n_il, n_xl, n_t), dtype=np.float32)
    for i in range(n_il):
        for k in range(n_t):
            block_i = (i // 4) % 2
            block_t = (k // 8) % 2
            sign = 1.0 if (block_i ^ block_t) else -1.0
            if k % 8 == 0:
                refl[i, :, k] = sign

    wavelet = _ricker(31, dt_ms, f_hz=24.0)
    data = _convolve_axis(refl, wavelet)
    rng = np.random.default_rng(seed=42)
    data += 0.02 * rng.standard_normal(data.shape).astype(np.float32)

    if path.exists():
        shutil.rmtree(path)
    ds = xr.Dataset(
        data_vars={"amplitude": (("inline", "crossline", "time"), data)},
        coords={"inline": inline, "crossline": crossline, "time": time},
        attrs={"defaultVariableName": "amplitude"},
    )
    ds.coords["time"].attrs["units"] = "ms"
    to_mdio(ds, str(path), mode="w")
    print(f"wrote {path} ({n_il}x{n_xl}x{n_t})")


def update_project_yaml(project_dir: Path) -> None:
    yaml_path = project_dir / "project.yaml"
    yaml_path.write_text(
        "name: eggseis demo\n"
        "surveys:\n"
        "  - name: demo\n"
        "    path: ../../demo.mdio\n"
        "  - name: wedge\n"
        "    path: wedge.mdio\n"
        "  - name: checkerboard\n"
        "    path: checkerboard.mdio\n"
        "horizons: []\n"
        "wells: []\n"
    )
    print(f"updated {yaml_path}")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    project_dir = repo_root / "examples" / "demo-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    build_wedge(project_dir / "wedge.mdio")
    build_checkerboard(project_dir / "checkerboard.mdio")
    update_project_yaml(project_dir)


if __name__ == "__main__":
    main()
