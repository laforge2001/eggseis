"""Well dataclass + HDF5 round-trip + LAS importer."""

from __future__ import annotations

import numpy as np
import pytest


def _basic_well():
    from eggseis.data.well import Well

    deviation = np.array([
        [0.0, 0.0, 0.0],     # md, x, y at surface
        [100.0, 5.0, 2.0],
        [200.0, 12.0, 8.0],
    ], dtype=np.float32)
    logs = {
        "GR": np.array([55.0, 60.5, 72.3], dtype=np.float32),
        "RHOB": np.array([2.4, 2.45, 2.5], dtype=np.float32),
    }
    return Well(
        name="Well-01",
        deviation=deviation,
        logs=logs,
        markers=[("Top reservoir", 150.0)],
        surface_xy=(1000.0, 2000.0),
    )


def test_well_dataclass_construction():
    well = _basic_well()
    assert well.name == "Well-01"
    assert well.deviation.shape == (3, 3)
    assert "GR" in well.logs
    assert well.markers == [("Top reservoir", 150.0)]


def test_well_save_load_round_trip(tmp_path):
    from eggseis.data.well import Well

    well = _basic_well()
    target = tmp_path / "wells" / "well_01.h5"
    well.save(target)
    assert target.exists()

    loaded = Well.load(target)
    assert loaded.name == "Well-01"
    np.testing.assert_array_equal(loaded.deviation, well.deviation)
    np.testing.assert_array_equal(loaded.logs["GR"], well.logs["GR"])
    np.testing.assert_array_equal(loaded.logs["RHOB"], well.logs["RHOB"])
    assert loaded.markers == well.markers
    assert loaded.surface_xy == well.surface_xy


def test_well_save_creates_parent_dir(tmp_path):
    well = _basic_well()
    target = tmp_path / "deeply" / "nested" / "well.h5"
    well.save(target)
    assert target.exists()


def test_las_importer_minimal(tmp_path):
    """Small synthetic LAS 2.0 → Well with one log."""
    from eggseis.data.well import import_las

    las_path = tmp_path / "synth.las"
    las_path.write_text(
        "~Version Information\n"
        "VERS.   2.0 :CWLS LOG ASCII STANDARD\n"
        "WRAP.   NO  :ONE LINE PER DEPTH STEP\n"
        "~Well Information\n"
        "STRT.M    100.0  :START DEPTH\n"
        "STOP.M    200.0  :STOP DEPTH\n"
        "STEP.M     50.0  :STEP\n"
        "NULL.    -999.25 :NULL VALUE\n"
        "WELL.    SYNTH-1 :WELL NAME\n"
        "~Curve Information\n"
        "DEPT.M  :DEPTH\n"
        "GR.GAPI :GAMMA RAY\n"
        "~ASCII\n"
        "100.0    55.0\n"
        "150.0    62.3\n"
        "200.0    71.0\n"
    )
    well = import_las(las_path, name="SYNTH-1", surface_xy=(100.0, 200.0))
    assert well.name == "SYNTH-1"
    assert "GR" in well.logs
    np.testing.assert_allclose(well.logs["GR"], [55.0, 62.3, 71.0], atol=1e-3)
    # Deviation: vertical-well default (n_md, 3) where x = y = 0 across MD.
    assert well.deviation.shape == (3, 3)
    np.testing.assert_array_equal(well.deviation[:, 0], [100.0, 150.0, 200.0])
    np.testing.assert_array_equal(well.deviation[:, 1:], 0.0)


def test_las_importer_null_values_become_nan(tmp_path):
    from eggseis.data.well import import_las

    las_path = tmp_path / "synth.las"
    las_path.write_text(
        "~V\nVERS. 2.0:\nWRAP.NO:\n"
        "~W\nSTRT.M 100.0:\nSTOP.M 200.0:\nSTEP.M 50.0:\nNULL. -999.25:\n"
        "WELL. NULLY:\n"
        "~C\nDEPT.M:\nGR.GAPI:\n"
        "~A\n"
        "100.0  55.0\n"
        "150.0  -999.25\n"
        "200.0  71.0\n"
    )
    well = import_las(las_path, name="NULLY", surface_xy=(0.0, 0.0))
    gr = well.logs["GR"]
    assert gr[0] == pytest.approx(55.0)
    assert np.isnan(gr[1])
    assert gr[2] == pytest.approx(71.0)
