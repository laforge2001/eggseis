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
    from eggseis.compute.cache import SectionLRU, make_cache_key
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
        make_cache_key(spec, params, vol, "inline", vol.geometry.inline_min),
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


def _make_sleep_spec(name: str, sleep_s: float):
    """Build a one-off `gain` plugin that sleeps `sleep_s` per trace."""
    import time as _time

    from eggseis.plugin import Param, trace_attribute

    @trace_attribute(name=name, version="0.1.0")
    def sleeper(trace, gain: float = Param(1.0, min=0.0, max=10.0)):
        _time.sleep(sleep_s)
        return (trace * gain).astype(np.float32)

    return sleeper._eggseis_spec


@pytest.fixture
def slow_spec():
    """5 ms per trace — long enough that delivery timer fires mid-job."""
    from eggseis.plugin import clear_registry
    clear_registry()
    yield _make_sleep_spec("Slow", 0.005)
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

    # Wait for the (single) post-debounce job to drain instead of sleeping.
    qtbot.waitUntil(lambda: orch._active is None and bool(sections), timeout=5000)
    assert len(sections) <= vol.geometry.n_inlines
    assert len(orch.cache) <= vol.geometry.n_inlines


@pytest.fixture
def very_slow_spec():
    """50 ms per trace — first job stays in flight long enough to be superseded."""
    from eggseis.plugin import clear_registry
    clear_registry()
    yield _make_sleep_spec("VerySlow", 0.05)
    clear_registry()


def test_supersede_cancels_in_flight_job(qtbot, fake_backend, very_slow_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    orch.request(very_slow_spec, very_slow_spec.param_model(),
                 vol, "inline", vol.geometry.inline_min)
    qtbot.waitUntil(lambda: orch._active is not None, timeout=2000)
    first_token = orch._active.token

    with qtbot.waitSignal(orch.sectionReady, timeout=20_000):
        orch.request(very_slow_spec, very_slow_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min + 1)

    assert first_token.cancelled is True


@pytest.fixture
def noise_spec():
    from eggseis.plugin import Param, clear_registry, trace_attribute
    clear_registry()

    @trace_attribute(name="Noise", version="0.1.0", deterministic=False)
    def noise(trace, gain: float = Param(1.0)):
        return np.random.default_rng().standard_normal(trace.shape).astype(np.float32)

    yield noise._eggseis_spec
    clear_registry()


def test_non_deterministic_plugin_is_not_cached(qtbot, fake_backend, noise_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    with qtbot.waitSignal(orch.sectionReady, timeout=5000):
        orch.request(noise_spec, noise_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)
    assert len(orch.cache) == 0


@pytest.fixture
def broken_spec():
    from eggseis.plugin import Param, clear_registry, trace_attribute
    clear_registry()

    @trace_attribute(name="Broken", version="0.1.0")
    def broken(trace, k: float = Param(1.0)):
        raise RuntimeError("nope")

    yield broken._eggseis_spec
    clear_registry()


def test_orchestrator_emits_failed_on_worker_exception(qtbot, fake_backend, broken_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    with qtbot.waitSignal(orch.failed, timeout=5000) as blocker:
        orch.request(broken_spec, broken_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)
    _job_id, msg = blocker.args
    assert "nope" in msg


def test_cache_hit_cancels_in_flight_job(qtbot, fake_backend, very_slow_spec):
    """A late tilesReady from a superseded job must not clobber a cached paint."""
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    # Prime cache with a fake result for inline_min + 1.
    from eggseis.compute.cache import make_cache_key
    pre = np.full(
        (vol.geometry.n_xlines, vol.geometry.n_samples), 9.0, dtype=np.float32
    )
    orch.cache.put(
        make_cache_key(
            very_slow_spec, very_slow_spec.param_model(), vol,
            "inline", vol.geometry.inline_min + 1,
        ),
        pre,
    )

    # Start a slow miss job for inline_min — must dispatch.
    orch.request(very_slow_spec, very_slow_spec.param_model(),
                 vol, "inline", vol.geometry.inline_min)
    qtbot.waitUntil(lambda: orch._active is not None, timeout=2000)
    first_token = orch._active.token

    # Cache-hit request supersedes the in-flight job.
    with qtbot.waitSignal(orch.sectionReady, timeout=1000):
        orch.request(very_slow_spec, very_slow_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min + 1)

    assert first_token.cancelled is True
    assert orch._active is None
