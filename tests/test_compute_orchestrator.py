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


def test_orchestrator_returns_from_cache_when_present(qtbot, fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.cache import CacheKey, SectionLRU, params_hash
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    params = spec.param_model()
    cache = SectionLRU()
    pre = np.full(
        (vol.geometry.n_xlines, vol.geometry.n_samples), 7.0, dtype=np.float32
    )
    cache.put(
        CacheKey(
            plugin_id=spec.id,
            plugin_version=spec.version,
            params_hash=params_hash(params.model_dump()),
            axis="inline",
            index=vol.geometry.inline_min,
            volume_version=vol.version,
        ),
        pre,
    )

    orch = JobOrchestrator(cache=cache)
    with qtbot.waitSignal(orch.sectionReady, timeout=1000) as blocker:
        orch.request(spec, params, vol, "inline", vol.geometry.inline_min)

    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, pre)


def test_orchestrator_computes_section_on_miss(qtbot, fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.plugin_runner import run_on_section

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=5000) as blocker:
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)

    _job_id, arr = blocker.args
    expected = run_on_section(
        spec, spec.param_model(), vol, "inline", vol.geometry.inline_min
    )
    np.testing.assert_allclose(arr, expected, rtol=1e-5)


def test_orchestrator_caches_after_compute(qtbot, fake_backend):
    import time

    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()

    with qtbot.waitSignal(orch.sectionReady, timeout=5000):
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    assert len(orch.cache) == 1

    t0 = time.perf_counter()
    with qtbot.waitSignal(orch.sectionReady, timeout=500):
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    assert (time.perf_counter() - t0) * 1000 < 200


@pytest.fixture
def slow_spec():
    """Per-trace sleep — long enough that delivery timer fires mid-job."""
    import time as _time

    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Slow", version="0.1.0")
    def slow(trace, gain: float = Param(1.0, min=0.0, max=10.0)):
        _time.sleep(0.005)
        return (trace * gain).astype(np.float32)

    yield slow._eggseis_spec
    clear_registry()


def test_orchestrator_emits_tiles_ready_progressively(qtbot, fake_backend, slow_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    tile_emissions: list[list[tuple[int, int]]] = []
    orch.tilesReady.connect(lambda _id, _buf, ranges: tile_emissions.append(list(ranges)))

    with qtbot.waitSignal(orch.sectionReady, timeout=10_000):
        orch.request(slow_spec, slow_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)

    assert tile_emissions, "tilesReady never fired before sectionReady"
    flat = sorted(r for batch in tile_emissions for r in batch)
    assert any(r[0] == 0 for r in flat)


def test_debounce_coalesces_rapid_requests(qtbot, fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()

    sections: list[int] = []
    orch.sectionReady.connect(lambda job_id, _arr: sections.append(job_id))

    for i in range(10):
        orch.request(spec, spec.param_model(), vol, "inline",
                     vol.geometry.inline_min + (i % vol.geometry.n_inlines))

    qtbot.wait(2000)
    assert len(sections) <= vol.geometry.n_inlines
    assert len(orch.cache) <= vol.geometry.n_inlines
