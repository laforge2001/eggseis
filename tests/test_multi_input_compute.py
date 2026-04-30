"""M6 step 4: multi-input plugin execution through compute_tile + orchestrator."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.axes import Axis
from eggseis.plugin import PluginSpec, clear_registry, graph_node
from eggseis.plugin_runner import compute_tile


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


# --- compute_tile, multi-input --------------------------------------------


def test_compute_tile_multi_input_dispatches_by_port_name():
    @graph_node(inputs=("a", "b"))
    def diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b

    spec = diff._eggseis_spec
    a = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    b = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    out = np.empty_like(a)
    compute_tile(
        spec,
        params_dump={},
        inputs={"a": a, "b": b},
        context={},
        start=0,
        stop=2,
        out=out,
    )
    np.testing.assert_array_equal(out, a - b)


def test_compute_tile_single_input_via_inputs_dict():
    @graph_node(inputs=("trace",))
    def echo(trace: np.ndarray) -> np.ndarray:
        return trace * 2

    spec = echo._eggseis_spec
    section = np.ones((4, 3), dtype=np.float32)
    out = np.empty_like(section)
    compute_tile(
        spec,
        params_dump={},
        inputs={"trace": section},
        context={},
        start=0,
        stop=4,
        out=out,
    )
    np.testing.assert_array_equal(out, section * 2)


def test_compute_tile_legacy_section_arg_still_works():
    """Back-compat: M3/M4/M5 callers pass a positional `section`, not `inputs`."""
    from eggseis.plugin import trace_attribute

    @trace_attribute(name="Echo")
    def echo(trace: np.ndarray) -> np.ndarray:
        return trace * 3

    spec = echo._eggseis_spec
    section = np.ones((4, 3), dtype=np.float32)
    out = np.empty_like(section)
    compute_tile(
        spec,
        params_dump={},
        section=section,
        context={},
        start=0,
        stop=4,
        out=out,
    )
    np.testing.assert_array_equal(out, section * 3)


# --- orchestrator multi-input ---------------------------------------------


def _make_passthrough_spec():
    """Single-input deterministic spec without registering — avoids fixture collision."""
    from pydantic import BaseModel, ConfigDict

    class P(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def func(trace):
        return trace

    return PluginSpec(
        id="tests.passthrough",
        name="Passthrough",
        func=func,
        param_model=P,
        params_decl={},
        vectorized=False,
        deterministic=True,
        version="0.1.0",
        source_path=None,
        accepts_context=False,
        inputs=("trace",),
    )


def test_orchestrator_request_input_sections_kwarg(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    @graph_node(inputs=("a", "b"))
    def diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b

    spec = diff._eggseis_spec
    volume = SeismicVolume(fake_backend)
    a = np.full((10, fake_backend.geometry.n_samples), 7.0, dtype=np.float32)
    b = np.full((10, fake_backend.geometry.n_samples), 2.0, dtype=np.float32)

    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        orch.request(
            spec, spec.param_model(),
            volume, Axis.INLINE,
            fake_backend.geometry.inline_min,
            input_sections={"a": a, "b": b},
        )
    _, arr = blocker.args
    np.testing.assert_allclose(arr, np.full_like(arr, 5.0))


def test_orchestrator_input_section_alias_preserved(qtbot, fake_backend):
    """Back-compat: M5 callers still pass input_section (singular)."""
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    spec = _make_passthrough_spec()
    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)
    section = (raw * 5).astype(np.float32)

    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        orch.request(
            spec, spec.param_model(),
            volume, Axis.INLINE,
            fake_backend.geometry.inline_min,
            input_section=section,
        )
    _, arr = blocker.args
    np.testing.assert_allclose(arr, section)


def test_orchestrator_no_inputs_falls_back_to_axis_read(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    spec = _make_passthrough_spec()
    volume = SeismicVolume(fake_backend)
    raw = volume.read_inline(fake_backend.geometry.inline_min)

    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        orch.request(spec, spec.param_model(), volume, Axis.INLINE,
                     fake_backend.geometry.inline_min)
    _, arr = blocker.args
    np.testing.assert_allclose(arr, raw)
