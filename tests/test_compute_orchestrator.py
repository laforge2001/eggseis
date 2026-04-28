"""Headless tests for the compute orchestrator + worker. Uses pytest-qt."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool

from eggseis.compute.job import Job
from eggseis.compute.tile import Tile
from eggseis.compute.worker import TileRunnable, TileSignals


@pytest.fixture
def envelope_spec_and_section(fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.data import SeismicVolume
    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    section = vol.read_inline(vol.geometry.inline_min).astype(np.float32)
    return spec, section


def test_tile_runnable_writes_into_job_output(qtbot, envelope_spec_and_section):
    spec, section = envelope_spec_and_section
    job = Job(
        spec=spec,
        params=spec.param_model(),
        section=section,
        output=np.zeros_like(section, dtype=np.float32),
        context={"sample_rate_ms": 4.0, "axis": "inline", "index": 100},
    )
    signals = TileSignals()
    tile = Tile(start=0, stop=section.shape[0], priority=0)

    with qtbot.waitSignal(signals.completed, timeout=2000) as blocker:
        QThreadPool.globalInstance().start(TileRunnable(job, tile, signals))

    job_id, start, stop = blocker.args
    assert job_id == job.id
    assert (start, stop) == (0, section.shape[0])
    assert (job.output != 0).any()


def test_tile_runnable_skips_when_token_already_cancelled(qtbot, envelope_spec_and_section):
    spec, section = envelope_spec_and_section
    job = Job(
        spec=spec,
        params=spec.param_model(),
        section=section,
        output=np.zeros_like(section, dtype=np.float32),
        context={"sample_rate_ms": 4.0, "axis": "inline", "index": 100},
    )
    job.token.cancel()
    signals = TileSignals()

    completed: list[tuple] = []
    signals.completed.connect(lambda *args: completed.append(args))

    QThreadPool.globalInstance().start(
        TileRunnable(job, Tile(start=0, stop=section.shape[0], priority=0), signals)
    )
    qtbot.wait(150)
    assert completed == []
    assert (job.output == 0).all()
