"""Synchronous plugin execution across the visible section."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec


def run_on_section(
    spec: PluginSpec,
    params: BaseModel,
    volume: SeismicVolume,
    axis: Axis | str,
    index: int,
) -> np.ndarray:
    """Run a trace-local plugin across every trace in the visible section.

    Returns an array shaped exactly like the source slice (no transpose).
    The viewer is responsible for any orientation it wants to apply.

    For timeslices, the slice is horizontal and trace-local attributes do
    not apply — the source array is returned unchanged.
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
    p = params.model_dump()

    if spec.vectorized:
        kwargs = dict(p)
        if spec.accepts_context:
            kwargs["context"] = context
        return spec.func(traces=section, **kwargs).astype(np.float32)

    out = np.empty_like(section, dtype=np.float32)
    for i in range(section.shape[0]):
        kwargs = dict(p)
        if spec.accepts_context:
            kwargs["context"] = context
        out[i] = spec.func(section[i], **kwargs)
    return out
