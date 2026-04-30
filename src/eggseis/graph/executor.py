"""GraphExecutor — coordinates JobOrchestrator across a DAG of plugin Nodes.

Walks the upstream cone of the tap port, looks up each output's chain_hash
in the orchestrator's cache, then topologically executes the cold subgraph.
A node fires when every input's array is in hand (cache hit OR completed
upstream orch job for that input).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal

from eggseis.axes import Axis
from eggseis.compute.cache import make_cache_key
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.graph.model import SOURCE_ID, Graph, read_source_at


class GraphExecutor(QObject):
    tapReady = Signal(int, object)                  # job_id, ndarray
    intermediateReady = Signal(int, str, str, object)  # job_id, node_id, port, ndarray
    failed = Signal(int, str)                        # job_id, message
    progress = Signal(int, int, str)                 # nodes_done, total_cold, plugin_name

    def __init__(self, orchestrator: JobOrchestrator) -> None:
        super().__init__()
        self._orch = orchestrator
        self._next_job_id = 0
        self._active_job_id: int | None = None
        self._active_on_ready = None
        self._active_on_failed = None

    # --- public API -----------------------------------------------------

    def request_tap(
        self,
        graph: Graph,
        volume: SeismicVolume,
        axis: Axis | str,
        index: int,
    ) -> None:
        self.cancel_active()
        axis_enum = Axis(axis) if not isinstance(axis, Axis) else axis
        tap_node, tap_port = graph.tap_port

        # Source tap: short-circuit to raw axis read.
        if tap_node == SOURCE_ID:
            arr = self._read_source_at(volume, tap_port, index)
            self.tapReady.emit(self._new_job_id(), arr)
            return

        # Timeslice axis: pipeline bypassed, paint raw.
        if axis_enum is Axis.TIMESLICE:
            self.tapReady.emit(self._new_job_id(), volume.read_timeslice(index))
            return

        # Pre-flight: confirm every needed input port is connected.
        cone = graph.upstream_cone(tap_node, tap_port)
        try:
            self._validate_cone(graph, cone)
        except ValueError as e:
            self.failed.emit(self._new_job_id(), str(e))
            return

        # Resolve cached outputs; collect cold nodes in topo order.
        resolved: dict[tuple[str, str], np.ndarray] = {}
        cold: list[str] = []
        for node_id in cone:
            if node_id == SOURCE_ID:
                continue  # Source ports lazily resolved when needed.
            node = graph.nodes[node_id]
            if not node.enabled:
                # Identity skip: forward parent's array under this node's hash.
                # We handle this by treating the disabled node as already
                # resolved via its parent (resolved at execution time).
                cold.append(node_id)
                continue
            chain_hash = graph.port_hash(node_id, "out", volume.version, axis_enum.value)
            key = make_cache_key(
                node.spec, node.params, volume, axis_enum, index, chain_hash=chain_hash,
            )
            if graph.deterministic_through(node_id, "out"):
                cached = self._orch.cache.get(key)
                if cached is not None:
                    resolved[(node_id, "out")] = cached
                    continue
            cold.append(node_id)

        # All cached: emit immediately.
        if not cold:
            self.tapReady.emit(self._new_job_id(), resolved[(tap_node, tap_port)])
            return

        self._run_cold(graph, volume, axis_enum, index, cold, resolved, tap_node, tap_port)

    def cancel_active(self) -> None:
        self._disconnect_active()
        self._orch.cancel_active()
        self._active_job_id = None

    # --- internals ------------------------------------------------------

    def _new_job_id(self) -> int:
        self._next_job_id += 1
        return self._next_job_id

    def _read_source_at(self, volume: SeismicVolume, port: str, index: int) -> np.ndarray:
        return read_source_at(volume, port, index)

    def _validate_cone(self, graph: Graph, cone: list[str]) -> None:
        """Reject the plan early if any node in the cone has dangling input ports.

        Both enabled and disabled nodes are checked: disabled identity-skip
        still requires the (single) input edge to compute the parent hash.
        """
        for node_id in cone:
            if node_id == SOURCE_ID:
                continue
            node = graph.nodes[node_id]
            incoming = graph.incoming_edges(node_id)
            for port in node.spec.inputs:
                if port not in incoming:
                    raise ValueError(
                        f"node {node.spec.name!r} input port {port!r} is unconnected"
                    )

    def _run_cold(
        self,
        graph: Graph,
        volume: SeismicVolume,
        axis: Axis,
        index: int,
        cold: list[str],
        resolved: dict[tuple[str, str], np.ndarray],
        tap_node: str,
        tap_port: str,
    ) -> None:
        job_id = self._new_job_id()
        self._active_job_id = job_id

        # Override request_tap's Source-tap branch: we always have an axis-read
        # to read from. Build a closure that pulls Source ports lazily.
        def source_arr(port: str) -> np.ndarray:
            return self._read_source_at(volume, port, index)

        cold_iter = iter(cold)

        def step() -> None:
            if self._active_job_id != job_id:
                return
            # Drain consecutive identity-skip (disabled) nodes synchronously
            # without recursion — keeps stack flat for long disabled chains.
            while True:
                try:
                    next_id = next(cold_iter)
                except StopIteration:
                    self.tapReady.emit(job_id, resolved[(tap_node, tap_port)])
                    self._active_job_id = None
                    return

                node = graph.nodes[next_id]
                incoming = graph.incoming_edges(next_id)

                if not node.enabled:
                    parent = incoming[node.spec.inputs[0]]
                    src_arr = (
                        source_arr(parent.src_port)
                        if parent.src_node_id == SOURCE_ID
                        else resolved[(parent.src_node_id, parent.src_port)]
                    )
                    resolved[(next_id, "out")] = src_arr
                    continue
                break

            # Build inputs dict for this node by port name.
            inputs: dict[str, np.ndarray] = {}
            for port_name in node.spec.inputs:
                edge = incoming[port_name]
                if edge.src_node_id == SOURCE_ID:
                    inputs[port_name] = source_arr(edge.src_port)
                else:
                    inputs[port_name] = resolved[(edge.src_node_id, edge.src_port)]

            chain_hash = graph.port_hash(next_id, "out", volume.version, axis.value)
            chain_det = graph.deterministic_through(next_id, "out")

            # Sink nodes run synchronously once at the section level — they
            # side-effect (e.g. write to disk) and pass their input through
            # without per-tile dispatch.
            if node.spec.kind == "sink":
                ctx = {
                    "sample_rate_ms": volume.geometry.sample_rate_ms,
                    "axis": axis.value,
                    "index": index,
                }
                params_dump = node.params.model_dump()
                kwargs = dict(inputs)
                kwargs.update(params_dump)
                if node.spec.accepts_context:
                    kwargs["context"] = ctx
                try:
                    out_arr = node.spec.func(**kwargs)
                except Exception as exc:
                    self._active_job_id = None
                    self.failed.emit(job_id, f"{node.spec.name}: {exc!r}")
                    return
                if out_arr is None:
                    out_arr = inputs[node.spec.inputs[0]]
                resolved[(next_id, "out")] = out_arr
                self.intermediateReady.emit(job_id, next_id, "out", out_arr)
                step()
                return

            def on_ready(_orch_job_id: int, arr: np.ndarray) -> None:
                if self._active_job_id != job_id:
                    return
                self._disconnect_active()
                resolved[(next_id, "out")] = arr
                self.intermediateReady.emit(job_id, next_id, "out", arr)
                step()

            def on_failed(_orch_job_id: int, message: str) -> None:
                if self._active_job_id != job_id:
                    return
                self._disconnect_active()
                self._active_job_id = None
                self.failed.emit(job_id, f"{node.spec.name}: {message}")

            self._active_on_ready = on_ready
            self._active_on_failed = on_failed
            self._orch.sectionReady.connect(on_ready)
            self._orch.failed.connect(on_failed)
            self._orch.request(
                node.spec, node.params, volume, axis, index,
                input_sections=inputs,
                chain_hash=chain_hash,
                skip_cache_write=not chain_det,
            )

        step()

    def _disconnect_active(self) -> None:
        if self._active_on_ready is not None:
            try:
                self._orch.sectionReady.disconnect(self._active_on_ready)
            except (TypeError, RuntimeError):
                pass
            self._active_on_ready = None
        if self._active_on_failed is not None:
            try:
                self._orch.failed.disconnect(self._active_on_failed)
            except (TypeError, RuntimeError):
                pass
            self._active_on_failed = None
