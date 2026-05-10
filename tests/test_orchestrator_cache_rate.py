"""JobOrchestrator emits cacheRateChanged when its hit/miss counters move.

This test exercises the signal directly rather than driving a full
request pipeline: the orchestrator is constructed, internal counters
are bumped, and we assert the signal fires with the rolling rate.
The end-to-end request path is covered by the existing
test_compute_orchestrator.py suite — we only need to prove the new
signal exists and reports the right number.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_cache_rate_emits_zero_after_first_miss(qtbot):
    from eggseis.compute.orchestrator import JobOrchestrator

    orch = JobOrchestrator()
    received: list[float] = []
    orch.cacheRateChanged.connect(received.append)

    orch._cache_misses += 1
    orch._emit_cache_rate()
    assert received == [0.0]


def test_cache_rate_emits_half_after_one_hit_one_miss(qtbot):
    from eggseis.compute.orchestrator import JobOrchestrator

    orch = JobOrchestrator()
    received: list[float] = []
    orch.cacheRateChanged.connect(received.append)

    orch._cache_misses += 1
    orch._emit_cache_rate()
    orch._cache_hits += 1
    orch._emit_cache_rate()

    assert received[-1] == pytest.approx(0.5)


def test_cache_rate_silent_when_no_activity(qtbot):
    from eggseis.compute.orchestrator import JobOrchestrator

    orch = JobOrchestrator()
    received: list[float] = []
    orch.cacheRateChanged.connect(received.append)

    orch._emit_cache_rate()
    assert received == []
