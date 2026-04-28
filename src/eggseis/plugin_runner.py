"""Synchronous plugin execution across the visible section."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec


def compute_tile(
    spec: PluginSpec,
    params_dump: dict[str, Any],
    section: np.ndarray,
    context: dict[str, Any],
    *,
    start: int,
    stop: int,
    out: np.ndarray,
) -> None:
    """Run `spec` over `section[start:stop]`, writing into `out[start:stop]`.

    Used directly by tile workers and indirectly (whole-section call) by
    the synchronous `run_on_section` below.
    """
    if spec.vectorized:
        kwargs = dict(params_dump)
        if spec.accepts_context:
            kwargs["context"] = context
        result = spec.func(traces=section[start:stop], **kwargs).astype(np.float32)
        out[start:stop] = result
        return

    for i in range(start, stop):
        kwargs = dict(params_dump)
        if spec.accepts_context:
            kwargs["context"] = context
        out[i] = spec.func(section[i], **kwargs)


def run_on_section(
    spec: PluginSpec,
    params: BaseModel,
    volume: SeismicVolume,
    axis: Axis | str,
    index: int,
) -> np.ndarray:
    """Run a trace-local plugin across every trace in the visible section.

    Synchronous; library/CLI use this. The GUI uses `JobOrchestrator` instead.

    For timeslices, trace-local attributes do not apply — the source array is
    returned unchanged.
    """
    axis = Axis(axis)
    if axis is Axis.INLINE:
        section = volume.read_inline(index)
    elif axis is Axis.XLINE:
        section = volume.read_xline(index)
    else:
        return volume.read_timeslice(index)

    g = volume.geometry
    context = {
        "sample_rate_ms": g.sample_rate_ms,
        "axis": axis.value,
        "index": index,
    }
    out = np.empty_like(section, dtype=np.float32)
    compute_tile(
        spec,
        params.model_dump(),
        section,
        context,
        start=0,
        stop=section.shape[0],
        out=out,
    )
    return out
