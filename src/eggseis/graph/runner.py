"""Synchronous graph runner — no Qt, no orchestrator, no thread pool.

Powers volume export and CLI usage. Walks the upstream cone of a tap
port in topological order, calling each node's function directly with
its declared inputs. Per-trace dispatch for non-vectorised plugins;
single call per section for vectorised + sink plugins.

This intentionally does NOT use the M4 cache, the M4 tile workers, or
the GraphExecutor's signal machinery. Designed for batch contexts
(loop over every inline, write to disk).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.graph.model import SOURCE_ID, Graph, read_source_at


def run_graph_on_section(
    graph: Graph,
    volume: SeismicVolume,
    axis: Axis | str,
    index: int,
    *,
    cone: list[str] | None = None,
) -> np.ndarray:
    """Walk graph.tap_port's upstream cone synchronously and return the section.

    Pass a precomputed `cone` to skip reverse-BFS + topo-sort on hot paths
    where the graph topology is invariant across `index` (e.g. volume export
    iterating every inline).
    """
    axis_enum = axis if isinstance(axis, Axis) else Axis(axis)
    tap_node, tap_port = graph.tap_port

    if axis_enum is Axis.TIMESLICE:
        return volume.read_timeslice(index)

    if tap_node == SOURCE_ID:
        return read_source_at(volume, tap_port, index)

    if cone is None:
        cone = graph.upstream_cone(tap_node, tap_port)
    resolved: dict[tuple[str, str], np.ndarray] = {}
    source_cache: dict[str, np.ndarray] = {}

    def _src(port: str) -> np.ndarray:
        arr = source_cache.get(port)
        if arr is None:
            arr = read_source_at(volume, port, index)
            source_cache[port] = arr
        return arr

    sample_rate = volume.geometry.sample_rate_ms
    base_context = {
        "sample_rate_ms": sample_rate,
        "axis": axis_enum.value,
        "index": index,
    }

    for node_id in cone:
        if node_id == SOURCE_ID:
            continue
        node = graph.nodes[node_id]
        incoming = graph.incoming_edges(node_id)

        # Disabled single-input identity skip.
        if not node.enabled:
            edge = incoming[node.spec.inputs[0]]
            src = (
                _src(edge.src_port)
                if edge.src_node_id == SOURCE_ID
                else resolved[(edge.src_node_id, edge.src_port)]
            )
            resolved[(node_id, "out")] = src
            continue

        # Build per-port inputs.
        port_inputs: dict[str, np.ndarray] = {}
        for port in node.spec.inputs:
            edge = incoming[port]
            if edge.src_node_id == SOURCE_ID:
                port_inputs[port] = _src(edge.src_port)
            else:
                port_inputs[port] = resolved[(edge.src_node_id, edge.src_port)]

        params_dump = node.params.model_dump()
        kwargs = dict(params_dump)
        if node.spec.accepts_context:
            kwargs["context"] = base_context

        if node.spec.kind == "sink" or node.spec.vectorized:
            # One section-level call (sinks side-effect; vectorised takes batch).
            result = node.spec.func(**port_inputs, **kwargs)
            if result is None:
                result = port_inputs[node.spec.inputs[0]]
            resolved[(node_id, "out")] = np.asarray(result, dtype=np.float32)
        else:
            # Per-trace scalar call. Inputs share the same first-axis length.
            n_traces = port_inputs[node.spec.inputs[0]].shape[0]
            sample_arr = node.spec.func(
                **{p: port_inputs[p][0] for p in node.spec.inputs},
                **kwargs,
            )
            out = np.empty((n_traces, *np.asarray(sample_arr).shape), dtype=np.float32)
            out[0] = sample_arr
            for i in range(1, n_traces):
                out[i] = node.spec.func(
                    **{p: port_inputs[p][i] for p in node.spec.inputs},
                    **kwargs,
                )
            resolved[(node_id, "out")] = out

    return resolved[(tap_node, tap_port)]


def export_volume_with_graph(
    graph: Graph,
    volume: SeismicVolume,
    out_path: str | Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Apply `graph` across every inline of `volume` and write a new MDIO.

    The graph's `tap_port` selects which node's output is written. An empty
    graph (Source-tap) writes the input volume unchanged. Output geometry
    matches the source volume.

    `on_progress(done, total)` fires after each inline is processed.
    """
    import xarray as xr
    from mdio import to_mdio

    out_path = Path(out_path).expanduser()
    if out_path.exists():
        if out_path.is_dir():
            shutil.rmtree(out_path)
        else:
            out_path.unlink()

    geometry = volume.geometry
    inline_axis = np.arange(
        geometry.inline_min,
        geometry.inline_min + geometry.n_inlines * geometry.inline_step,
        geometry.inline_step,
        dtype=np.int32,
    )
    xline_axis = np.arange(
        geometry.xline_min,
        geometry.xline_min + geometry.n_xlines * geometry.xline_step,
        geometry.xline_step,
        dtype=np.int32,
    )
    time_axis = (np.arange(geometry.n_samples, dtype=np.float32) * geometry.sample_rate_ms)

    n_bytes = geometry.n_inlines * geometry.n_xlines * geometry.n_samples * 4
    if n_bytes > 8 * 1024 ** 3:  # 8 GB
        raise MemoryError(
            f"Export would allocate {n_bytes / 1024**3:.1f} GB in RAM "
            "(in-memory cube cap is 8 GB). Streaming export is on the M7+ roadmap."
        )

    # Topology is invariant across inline index; resolve cone once.
    tap_node, tap_port = graph.tap_port
    if tap_node == SOURCE_ID:
        cone = None
    else:
        cone = graph.upstream_cone(tap_node, tap_port)

    cube = np.empty(
        (geometry.n_inlines, geometry.n_xlines, geometry.n_samples), dtype=np.float32
    )
    total = geometry.n_inlines
    for k, inline in enumerate(inline_axis):
        section = run_graph_on_section(
            graph, volume, Axis.INLINE, int(inline), cone=cone
        )
        cube[k] = section.astype(np.float32, copy=False)
        if on_progress is not None:
            on_progress(k + 1, total)

    ds = xr.Dataset(
        data_vars={"amplitude": (("inline", "crossline", "time"), cube)},
        coords={"inline": inline_axis, "crossline": xline_axis, "time": time_axis},
        attrs={"defaultVariableName": "amplitude"},
    )
    ds.coords["time"].attrs["units"] = "ms"
    to_mdio(ds, str(out_path), mode="w")
