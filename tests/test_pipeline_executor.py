"""PipelineExecutor tests — qtbot-driven; require pytest-qt."""

from __future__ import annotations

import numpy as np

from eggseis.pipeline.model import Node, Pipeline


def test_empty_pipeline_taps_source_emits_raw(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)
    p = Pipeline()  # tap defaults to SOURCE_ID

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, volume.read_inline(volume.geometry.inline_min))


def test_single_node_cold_execution(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline((linear_spec, linear_spec.param_model(scale=2.0)))
    p.set_tap(p.nodes[0].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    np.testing.assert_allclose(
        arr,
        volume.read_inline(volume.geometry.inline_min) * 2.0,
        rtol=1e-5,
    )


def test_three_node_chain_executes_serially(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
        (linear_spec, linear_spec.param_model(scale=5.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=10_000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 30.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)


def test_warm_tap_returns_cached_output(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    # Warm.
    with qtbot.waitSignal(exe.tapReady, timeout=5000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)

    # Second request: should hit cache. Tight timeout — generous for CI but
    # tight enough that a re-compute would miss it.
    with qtbot.waitSignal(exe.tapReady, timeout=200) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 6.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)


def test_param_edit_on_middle_node_invalidates_only_downstream(
    qtbot, fake_backend, linear_spec, make_pipeline
):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
        (linear_spec, linear_spec.param_model(scale=5.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    # Warm whole chain.
    with qtbot.waitSignal(exe.tapReady, timeout=5000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    cache_size_after_warm = len(orch.cache)
    assert cache_size_after_warm == 3  # 3 entries: node 1, 2, 3

    # Edit middle node param.
    p.set_params(p.nodes[1].node_id, linear_spec.param_model(scale=7.0))

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 2.0 * 7.0 * 5.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)

    # Cache now has 5 entries: node 1 (unchanged), old node 2/3, new node 2/3.
    assert len(orch.cache) == 5
