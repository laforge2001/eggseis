"""Tests for the M6 @graph_node decorator (multi-input plugin API)."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.plugin import Param, clear_registry


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_registry()
    yield
    clear_registry()


def test_graph_node_single_input_registers_spec():
    from eggseis.plugin import graph_node, registered

    @graph_node(name="Echo", version="0.2.0", inputs=("trace",))
    def echo(trace: np.ndarray) -> np.ndarray:
        return trace

    spec = echo._eggseis_spec
    assert spec.name == "Echo"
    assert spec.version == "0.2.0"
    assert spec.inputs == ("trace",)
    assert spec.output == "out"
    assert spec.deterministic is True
    assert spec.vectorized is False
    assert spec in registered()


def test_graph_node_multi_input_declares_named_ports():
    from eggseis.plugin import graph_node

    @graph_node(name="Subtract", inputs=("a", "b"))
    def subtract(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b

    assert subtract._eggseis_spec.inputs == ("a", "b")


def test_graph_node_params_still_pydantic():
    from eggseis.plugin import graph_node

    @graph_node(name="Scale", inputs=("trace",))
    def scale(trace: np.ndarray, factor: float = Param(default=2.0)) -> np.ndarray:
        return trace * factor

    pm = scale._eggseis_spec.param_model
    inst = pm()
    assert inst.factor == 2.0
    inst2 = pm(factor=5.0)
    assert inst2.factor == 5.0


def test_graph_node_input_arg_skips_param_check():
    """Input ports must NOT require Param() defaults."""
    from eggseis.plugin import graph_node

    # Should not raise — `a` and `b` are declared as input ports.
    @graph_node(inputs=("a", "b"))
    def add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a + b

    assert add._eggseis_spec.inputs == ("a", "b")


def test_graph_node_non_input_arg_must_have_param_default():
    from eggseis.plugin import graph_node

    with pytest.raises(TypeError, match="must declare a Param"):
        @graph_node(inputs=("trace",))
        def bad(trace: np.ndarray, factor: float = 2.0) -> np.ndarray:
            return trace * factor


def test_graph_node_accepts_context_flag():
    from eggseis.plugin import graph_node

    @graph_node(inputs=("trace",))
    def with_ctx(trace: np.ndarray, context: dict | None = None) -> np.ndarray:
        return trace

    assert with_ctx._eggseis_spec.accepts_context is True


def test_graph_node_runs_function_correctly():
    from eggseis.plugin import graph_node

    @graph_node(inputs=("a", "b"))
    def sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a - b

    a = np.array([3.0, 5.0, 7.0])
    b = np.array([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(sub._eggseis_spec.func(a, b), [2.0, 3.0, 4.0])


def test_trace_attribute_still_populates_inputs():
    """Backwards compat — @trace_attribute continues to work."""
    from eggseis.plugin import trace_attribute

    @trace_attribute(name="Echo")
    def echo(trace: np.ndarray) -> np.ndarray:
        return trace

    assert echo._eggseis_spec.inputs == ("trace",)
    assert echo._eggseis_spec.output == "out"


def test_trace_attribute_vectorized_uses_traces_input_name():
    from eggseis.plugin import trace_attribute

    @trace_attribute(name="Echo", vectorized=True)
    def echo(traces: np.ndarray) -> np.ndarray:
        return traces

    assert echo._eggseis_spec.inputs == ("traces",)


def test_graph_node_deterministic_default_true():
    from eggseis.plugin import graph_node

    @graph_node(inputs=("trace",))
    def f(trace: np.ndarray) -> np.ndarray:
        return trace

    assert f._eggseis_spec.deterministic is True


def test_graph_node_deterministic_false_propagates():
    from eggseis.plugin import graph_node

    @graph_node(inputs=("trace",), deterministic=False)
    def noise(trace: np.ndarray) -> np.ndarray:
        return trace

    assert noise._eggseis_spec.deterministic is False
