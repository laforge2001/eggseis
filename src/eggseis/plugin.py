"""Plugin API: @trace_attribute (single-input) and @graph_node (multi-input)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, create_model


class PluginRegistrationError(Exception):
    """Raised when a plugin decorator is misconfigured at decoration time."""


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
    inputs: tuple[str, ...] = ("trace",)
    output: str = "out"
    kind: Literal["transform", "sink"] = "transform"
    cmap: str | None = None


_RESERVED_TRACE = ("trace", "traces", "context")
_REGISTRY: dict[str, PluginSpec] = {}


def _build_spec(
    func: Callable[..., np.ndarray],
    *,
    name: str | None,
    version: str,
    inputs: tuple[str, ...],
    vectorized: bool,
    deterministic: bool,
    kind: Literal["transform", "sink"] = "transform",
) -> PluginSpec:
    sig = inspect.signature(func)
    fields: dict[str, tuple[type, Any]] = {}
    params_decl: dict[str, Param] = {}
    accepts_context = "context" in sig.parameters
    skip = set(inputs) | {"context"}

    for pname, param in sig.parameters.items():
        if pname in skip:
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
    return PluginSpec(
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
        inputs=inputs,
        kind=kind,
    )


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
        input_port = "traces" if vectorized else "trace"
        spec = _build_spec(
            func,
            name=name,
            version=version,
            inputs=(input_port,),
            vectorized=vectorized,
            deterministic=deterministic,
        )
        _REGISTRY[spec.id] = spec
        func._eggseis_spec = spec  # type: ignore[attr-defined]
        return func

    return decorator


def graph_node(
    *,
    name: str | None = None,
    version: str = "0.1.0",
    inputs: tuple[str, ...] = ("input",),
    deterministic: bool = True,
    kind: Literal["transform", "sink"] = "transform",
) -> Callable[[Callable[..., np.ndarray]], Callable[..., np.ndarray]]:
    """Decorate a function as a graph-node plugin with N named input ports.

    Each name in `inputs` must match a positional or keyword argument of the
    function. The function receives those args as `np.ndarray` per port and
    returns a single ndarray on output port `"out"`. Non-input args with a
    `Param(...)` default become pydantic fields. An optional `context` arg
    is treated as the per-call sidecar dict (same shape as `@trace_attribute`).
    """

    def decorator(func: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
        sig = inspect.signature(func)
        for input_name in inputs:
            if input_name not in sig.parameters:
                raise TypeError(
                    f"{func.__name__}: declared input port {input_name!r} "
                    f"is not a parameter of the function"
                )
        spec = _build_spec(
            func,
            name=name,
            version=version,
            inputs=inputs,
            vectorized=False,
            deterministic=deterministic,
            kind=kind,
        )
        _REGISTRY[spec.id] = spec
        func._eggseis_spec = spec  # type: ignore[attr-defined]
        return func

    return decorator


def plugin(
    *,
    name: str,
    version: str = "0.1.0",
    inputs: tuple[str, ...] = ("section",),
    vectorized: bool = False,
    deterministic: bool = True,
    kind: Literal["transform", "sink"] = "transform",
    cmap: str | None = None,
) -> Callable[[Callable[..., np.ndarray]], Callable[..., np.ndarray]]:
    """Decorate a function as a named plugin, registered under ``name``.

    This is the recommended high-level decorator. Unlike ``@trace_attribute``
    and ``@graph_node`` (which key the registry by ``module.func``), this
    decorator stores the entry under the ``name`` string so it can be looked up
    by display name.

    ``cmap`` is an optional default colormap name.  It is validated eagerly at
    decoration time against ``eggseis.colormaps.LUTS_AVAILABLE``; an unknown
    value raises :class:`PluginRegistrationError`.
    """
    if cmap is not None:
        from eggseis.colormaps import LUTS_AVAILABLE

        if cmap not in LUTS_AVAILABLE:
            raise PluginRegistrationError(
                f"@plugin(name={name!r}) cmap={cmap!r} not in {LUTS_AVAILABLE}"
            )

    def decorator(func: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
        spec = _build_spec(
            func,
            name=name,
            version=version,
            inputs=inputs,
            vectorized=vectorized,
            deterministic=deterministic,
            kind=kind,
        )
        # Replace the auto-generated spec with one that carries cmap.
        spec_with_cmap = PluginSpec(
            id=spec.id,
            name=spec.name,
            func=spec.func,
            param_model=spec.param_model,
            params_decl=spec.params_decl,
            vectorized=spec.vectorized,
            deterministic=spec.deterministic,
            version=spec.version,
            source_path=spec.source_path,
            accepts_context=spec.accepts_context,
            inputs=spec.inputs,
            output=spec.output,
            kind=spec.kind,
            cmap=cmap,
        )
        _REGISTRY[name] = spec_with_cmap
        func._eggseis_spec = spec_with_cmap  # type: ignore[attr-defined]
        return func

    return decorator


def registered() -> tuple[PluginSpec, ...]:
    return tuple(_REGISTRY.values())


def get(plugin_id: str) -> PluginSpec:
    return _REGISTRY[plugin_id]


def clear_registry() -> None:
    """Test helper. Don't call from app code."""
    _REGISTRY.clear()
