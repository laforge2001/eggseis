"""Tests for the @trace_attribute decorator and Param declarations."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from eggseis.plugin import (
    Param,
    clear_registry,
    get,
    registered,
    trace_attribute,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_decorator_registers_spec_with_default_name():
    @trace_attribute()
    def my_attribute(trace: np.ndarray, k: float = Param(2.0)):
        return trace * k

    specs = registered()
    assert len(specs) == 1
    spec = specs[0]
    assert spec.func is my_attribute
    assert spec.name == "My Attribute"  # default: snake_case → Title Case
    assert spec.version == "0.1.0"
    assert spec.vectorized is False
    assert spec.deterministic is True
    assert spec.accepts_context is False


def test_decorator_explicit_name_and_version():
    @trace_attribute(name="Custom Name", version="1.2.3")
    def whatever(trace: np.ndarray, k: float = Param(1.0)):
        return trace

    spec = registered()[0]
    assert spec.name == "Custom Name"
    assert spec.version == "1.2.3"


def test_param_model_carries_defaults_and_bounds():
    @trace_attribute()
    def gain(
        trace: np.ndarray,
        k: float = Param(2.0, min=0.0, max=10.0, label="Gain factor"),
    ):
        return trace * k

    spec = registered()[0]
    model = spec.param_model()
    assert model.k == 2.0

    # bounds enforced by pydantic
    with pytest.raises(ValidationError):
        spec.param_model(k=99.0)
    with pytest.raises(ValidationError):
        spec.param_model(k=-1.0)


def test_param_extra_forbidden():
    @trace_attribute()
    def f(trace: np.ndarray, k: float = Param(1.0)):
        return trace

    spec = registered()[0]
    with pytest.raises(ValidationError):
        spec.param_model(k=1.0, unknown=42)


def test_param_without_param_default_raises():
    with pytest.raises(TypeError, match="must declare a Param"):

        @trace_attribute()
        def bad(trace: np.ndarray, k: float = 2.0):
            return trace


def test_context_arg_detected():
    @trace_attribute()
    def with_ctx(
        trace: np.ndarray,
        context: dict,
        k: float = Param(1.0),
    ):
        return trace

    spec = registered()[0]
    assert spec.accepts_context is True


def test_reserved_args_skipped_from_param_model():
    @trace_attribute()
    def f(
        trace: np.ndarray,
        context: dict,
        k: float = Param(1.0),
    ):
        return trace

    spec = registered()[0]
    fields = spec.param_model.model_fields
    assert "k" in fields
    assert "trace" not in fields
    assert "context" not in fields


def test_get_by_id():
    @trace_attribute()
    def f(trace: np.ndarray, k: float = Param(1.0)):
        return trace

    spec = registered()[0]
    assert get(spec.id) is spec


def test_func_carries_spec_attribute():
    @trace_attribute()
    def f(trace: np.ndarray, k: float = Param(1.0)):
        return trace

    assert f._eggseis_spec.id.endswith(".f")


def test_vectorized_flag_propagates():
    @trace_attribute(vectorized=True)
    def f(traces: np.ndarray, k: float = Param(1.0)):
        return traces

    spec = registered()[0]
    assert spec.vectorized is True
