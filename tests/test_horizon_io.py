"""Horizon dataclass + I/O round-trip + XYZ CSV importer."""

from __future__ import annotations

import numpy as np
import pytest


def _grid_32_24() -> np.ndarray:
    return np.fromfunction(
        lambda i, j: 50.0 + 1.5 * i + 0.7 * j,
        (32, 24),
        dtype=np.float32,
    )


def test_horizon_dataclass_construction():
    from eggseis.data.horizon import Horizon

    h = Horizon(name="top", grid=_grid_32_24(), geometry_ref="../wedge.mdio")
    assert h.name == "top"
    assert h.grid.shape == (32, 24)
    assert h.color == "#ffcc00"  # default
    assert h.unit == "ms"


def test_horizon_save_then_load_round_trip(tmp_path):
    from eggseis.data.horizon import Horizon

    grid = _grid_32_24()
    h = Horizon(name="top", grid=grid, geometry_ref="../wedge.mdio", color="#ff0000")
    target = tmp_path / "horizons" / "top"
    h.save(target)

    assert (target / "horizon").exists()
    assert (target / "sidecar.json").exists()

    loaded = Horizon.load(target)
    assert loaded.name == "top"
    assert loaded.color == "#ff0000"
    assert loaded.geometry_ref == "../wedge.mdio"
    np.testing.assert_array_equal(loaded.grid, grid)


def test_horizon_value_at_returns_float(tmp_path):
    from eggseis.data.horizon import Horizon

    grid = _grid_32_24()
    h = Horizon(
        name="top",
        grid=grid,
        geometry_ref="x",
        inline_min=100,
        xline_min=300,
    )
    # inline 102 (idx 2), xline 301 (idx 1) → 50.0 + 1.5*2 + 0.7*1 = 53.7
    assert h.value_at(102, 301) == pytest.approx(53.7, abs=1e-3)


def test_horizon_value_at_nan_returns_none():
    from eggseis.data.horizon import Horizon

    grid = _grid_32_24().copy()
    grid[5, 5] = np.nan
    h = Horizon(
        name="top",
        grid=grid,
        geometry_ref="x",
        inline_min=100,
        xline_min=300,
    )
    assert h.value_at(105, 305) is None


def test_horizon_value_at_out_of_bounds_returns_none():
    from eggseis.data.horizon import Horizon

    h = Horizon(
        name="top",
        grid=_grid_32_24(),
        geometry_ref="x",
        inline_min=100,
        xline_min=300,
    )
    assert h.value_at(200, 300) is None  # inline far out of range


def test_xyz_csv_importer_basic(tmp_path):
    """XYZ CSV: three columns inline, xline, time(ms). Import to a Horizon
    grid sized to the survey geometry."""
    from eggseis.data.horizon import import_xyz_csv

    csv = tmp_path / "horizon.csv"
    csv.write_text(
        "inline,xline,time\n"
        "100,300,55.0\n"
        "100,301,55.7\n"
        "101,300,56.5\n"
        "101,301,57.2\n"
    )
    h = import_xyz_csv(
        csv,
        name="top",
        inline_min=100, n_inlines=2, inline_step=1,
        xline_min=300, n_xlines=2, xline_step=1,
        geometry_ref="../survey.mdio",
    )
    np.testing.assert_array_equal(h.grid, np.array([[55.0, 55.7], [56.5, 57.2]], dtype=np.float32))


def test_xyz_csv_missing_samples_become_nan(tmp_path):
    from eggseis.data.horizon import import_xyz_csv

    csv = tmp_path / "horizon.csv"
    # Only one corner provided.
    csv.write_text("inline,xline,time\n100,300,55.0\n")
    h = import_xyz_csv(
        csv,
        name="top",
        inline_min=100, n_inlines=2, inline_step=1,
        xline_min=300, n_xlines=2, xline_step=1,
        geometry_ref="../s.mdio",
    )
    assert h.grid[0, 0] == pytest.approx(55.0)
    assert np.isnan(h.grid[0, 1])
    assert np.isnan(h.grid[1, 0])
    assert np.isnan(h.grid[1, 1])


def test_xyz_csv_skips_out_of_geometry_samples(tmp_path):
    """Samples whose inline/xline are outside the survey geometry are dropped."""
    from eggseis.data.horizon import import_xyz_csv

    csv = tmp_path / "horizon.csv"
    csv.write_text(
        "inline,xline,time\n"
        "100,300,55.0\n"
        "999,999,99.0\n"  # out of geometry — silently dropped
    )
    h = import_xyz_csv(
        csv,
        name="top",
        inline_min=100, n_inlines=1, inline_step=1,
        xline_min=300, n_xlines=1, xline_step=1,
        geometry_ref="x",
    )
    assert h.grid.shape == (1, 1)
    assert h.grid[0, 0] == pytest.approx(55.0)


def test_opendtect_ascii_importer_basic(tmp_path):
    """OpendTect ASCII: comment lines start with '#' or '"'; data is whitespace-
    separated columns. Default column order: inline xline X Y time."""
    from eggseis.data.horizon import import_opendtect_ascii

    f = tmp_path / "horizon.txt"
    f.write_text(
        '"Horizon export from OpendTect"\n'
        "# Inline Crossline X Y Z\n"
        "100 300 1000.0 2000.0 55.0\n"
        "100 301 1010.0 2000.0 55.7\n"
        "101 300 1000.0 2010.0 56.5\n"
        "101 301 1010.0 2010.0 57.2\n"
    )
    h = import_opendtect_ascii(
        f,
        name="top",
        inline_min=100, n_inlines=2, inline_step=1,
        xline_min=300, n_xlines=2, xline_step=1,
        geometry_ref="../survey.mdio",
    )
    np.testing.assert_array_equal(
        h.grid, np.array([[55.0, 55.7], [56.5, 57.2]], dtype=np.float32)
    )


def test_opendtect_ascii_skips_blank_lines(tmp_path):
    from eggseis.data.horizon import import_opendtect_ascii

    f = tmp_path / "horizon.txt"
    f.write_text(
        "# header\n"
        "\n"
        "100 300 1000.0 2000.0 55.0\n"
        "\n"
        "100 301 1010.0 2000.0 55.7\n"
    )
    h = import_opendtect_ascii(
        f,
        name="top",
        inline_min=100, n_inlines=1, inline_step=1,
        xline_min=300, n_xlines=2, xline_step=1,
        geometry_ref="x",
    )
    np.testing.assert_array_equal(h.grid, np.array([[55.0, 55.7]], dtype=np.float32))


def test_opendtect_ascii_handles_three_column_input(tmp_path):
    """Some exports lack X/Y — just inline xline time. Importer auto-detects."""
    from eggseis.data.horizon import import_opendtect_ascii

    f = tmp_path / "horizon.txt"
    f.write_text("100 300 55.0\n100 301 55.7\n")
    h = import_opendtect_ascii(
        f,
        name="top",
        inline_min=100, n_inlines=1, inline_step=1,
        xline_min=300, n_xlines=2, xline_step=1,
        geometry_ref="x",
    )
    np.testing.assert_array_equal(h.grid, np.array([[55.0, 55.7]], dtype=np.float32))


def test_import_xyz_csv_autodetect_finds_bounds(tmp_path):
    """Auto-detect importer infers inline/xline bounds from the CSV data
    and builds a tightly fitted grid (step assumed 1)."""
    from eggseis.data.horizon import import_xyz_csv_autodetect

    csv = tmp_path / "horizon.csv"
    csv.write_text(
        "inline,xline,time\n"
        "100,300,55.0\n"
        "100,302,55.7\n"
        "102,300,56.5\n"
        "102,302,57.2\n"
    )
    h = import_xyz_csv_autodetect(
        csv,
        name="top",
        geometry_ref="(detached)",
    )
    assert h.inline_min == 100
    assert h.xline_min == 300
    assert h.inline_step == 1
    assert h.xline_step == 1
    # Bounds: inline 100-102 => 3 inlines; xline 300-302 => 3 xlines.
    assert h.grid.shape == (3, 3)
    assert h.grid[0, 0] == pytest.approx(55.0)
    assert h.grid[2, 2] == pytest.approx(57.2)
    # Cells with no sample stay NaN.
    assert np.isnan(h.grid[1, 1])
    assert h.geometry_ref == "(detached)"


def test_import_xyz_csv_autodetect_empty_raises(tmp_path):
    from eggseis.data.horizon import import_xyz_csv_autodetect

    csv = tmp_path / "horizon.csv"
    csv.write_text("inline,xline,time\n")
    with pytest.raises(ValueError, match="no data rows"):
        import_xyz_csv_autodetect(csv, name="top", geometry_ref="x")


def test_save_creates_parent_directories(tmp_path):
    from eggseis.data.horizon import Horizon

    h = Horizon(name="top", grid=_grid_32_24(), geometry_ref="x")
    target = tmp_path / "deeply" / "nested" / "horizons" / "top"
    h.save(target)
    assert (target / "horizon").exists()
