"""PipelineExecutor tests — qtbot-driven; require pytest-qt."""

from __future__ import annotations

import numpy as np


def test_empty_pipeline_taps_source_emits_raw(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor
    from eggseis.pipeline.model import Pipeline

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)
    p = Pipeline()  # tap defaults to SOURCE_ID

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, volume.read_inline(volume.geometry.inline_min))
