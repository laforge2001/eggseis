"""Plugin API: @trace_attribute decorator and Param declarations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, create_model


@dataclass(frozen=True)
class Param:
    """User-facing parameter declaration. Translated into a pydantic field."""

    default: Any
    label: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    units: str | None = None
    description: str | None = None
    choices: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class PluginSpec:
    id: str
    name: str
    func: Callable[..., np.ndarray]
    param_model: type[BaseModel]
    params_decl: dict[str, Param]
    vectorized: bool
    deterministic: bool
    version: str
    source_path: str | None
    accepts_context: bool


_RESERVED = ("trace", "traces", "context")
_REGISTRY: dict[str, PluginSpec] = {}


def trace_attribute(
    *,
    name: str | None = None,
    version: str = "0.1.0",
    vectorized: bool = False,
    deterministic: bool = True,
) -> Callable[[Callable[..., np.ndarray]], Callable[..., np.ndarray]]:
    """Decorate a function as a trace-local seismic attribute.

    The function signature determines the parameter dialog. Each non-trace
    argument with a `Param(...)` default becomes a pydantic field. The first
    positional argument (`trace` for scalar mode, `traces` for vectorized)
    and an optional `context` dict are treated specially.
    """

    def decorator(func: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
        sig = inspect.signature(func)
        fields: dict[str, tuple[type, Any]] = {}
        params_decl: dict[str, Param] = {}
        accepts_context = "context" in sig.parameters

        for pname, param in sig.parameters.items():
            if pname in _RESERVED:
                continue
            if not isinstance(param.default, Param):
                raise TypeError(
                    f"{func.__name__}: parameter {pname!r} must declare a "
                    f"Param(...) default"
                )
            p: Param = param.default
            params_decl[pname] = p
            if param.annotation is not inspect.Parameter.empty:
                ftype = param.annotation
            else:
                ftype = type(p.default)
            field = Field(
                default=p.default,
                title=p.label or pname,
                description=p.description,
                ge=p.min,
                le=p.max,
                json_schema_extra={
                    "step": p.step,
                    "units": p.units,
                    "choices": list(p.choices) if p.choices else None,
                },
            )
            fields[pname] = (ftype, field)

        model = create_model(
            f"{func.__name__.title().replace('_', '')}Params",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )

        plugin_id = f"{func.__module__}.{func.__name__}"
        spec = PluginSpec(
            id=plugin_id,
            name=name or func.__name__.replace("_", " ").title(),
            func=func,
            param_model=model,
            params_decl=params_decl,
            vectorized=vectorized,
            deterministic=deterministic,
            version=version,
            source_path=getattr(inspect.getmodule(func), "__file__", None),
            accepts_context=accepts_context,
        )
        _REGISTRY[plugin_id] = spec
        func._eggseis_spec = spec  # type: ignore[attr-defined]
        return func

    return decorator


def registered() -> tuple[PluginSpec, ...]:
    return tuple(_REGISTRY.values())


def get(plugin_id: str) -> PluginSpec:
    return _REGISTRY[plugin_id]


def clear_registry() -> None:
    """Test helper. Don't call from app code."""
    _REGISTRY.clear()
