"""PipelineExecutor — coordinates JobOrchestrator across a chain of Nodes.

Owns no compute itself. Walks the pipeline up to the tap, looks up each
node's chain_hash in the orchestrator's cache, and serially issues
orch.request() calls for the cold suffix. Emits tapReady when the tap
node's output is in hand.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal

from eggseis.axes import Axis
from eggseis.compute.cache import make_cache_key
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


class PipelineExecutor(QObject):
    tapReady = Signal(int, object)               # job_id, ndarray
    intermediateReady = Signal(int, str, object)  # job_id, node_id, ndarray
    failed = Signal(int, str)                     # job_id, message
    progress = Signal(int, int, str)             # current_index (1-based), total, plugin_name

    def __init__(self, orchestrator: JobOrchestrator) -> None:
        super().__init__()
        self._orch = orchestrator
        self._next_job_id = 0
        self._active_job_id: int | None = None
        self._active_on_ready = None
        self._active_on_failed = None

    def _new_job_id(self) -> int:
        self._next_job_id += 1
        return self._next_job_id

    def cancel_active(self) -> None:
        """Drop pending chain steps + disconnect active slots + cancel orchestrator job."""
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
        self._orch.cancel_active()
        self._active_job_id = None

    def request_tap(
        self,
        pipeline: Pipeline,
        volume: SeismicVolume,
        axis: Axis | str,
        index: int,
    ) -> None:
        # Cancel any in-flight chain before starting a new plan.
        self.cancel_active()

        axis_enum = Axis(axis) if not isinstance(axis, Axis) else axis

        if axis_enum is Axis.TIMESLICE:
            self.tapReady.emit(self._new_job_id(), volume.read_timeslice(index))
            return

        plan = pipeline.nodes_up_to_tap()

        # Source / empty plan: raw paint.
        if not plan or pipeline.tap_node_id == SOURCE_ID:
            raw = self._read_raw(volume, axis_enum, index)
            self.tapReady.emit(self._new_job_id(), raw)
            return

        cache = self._orch.cache
        starting_input: np.ndarray | None = None
        cold_start_idx = 0
        for i in range(len(plan) - 1, -1, -1):
            node = plan[i]
            chain_hash = pipeline.chain_hash_for(node.node_id, volume.version)
            key = make_cache_key(
                node.spec, node.params, volume, axis_enum, index,
                chain_hash=chain_hash,
            )
            if pipeline.deterministic_through(node.node_id):
                cached = cache.get(key)
                if cached is not None:
                    if i == len(plan) - 1:
                        self.tapReady.emit(self._new_job_id(), cached)
                        return
                    starting_input = cached
                    cold_start_idx = i + 1
                    break

        if starting_input is None:
            starting_input = self._read_raw(volume, axis_enum, index)
            # cold_start_idx stays 0 from initialization

        cold_nodes = plan[cold_start_idx:]
        self._run_chain(pipeline, volume, axis_enum, index, cold_nodes, starting_input)

    def _run_chain(
        self,
        pipeline: Pipeline,
        volume: SeismicVolume,
        axis: Axis,
        index: int,
        cold_nodes: list[Node],
        starting_input: np.ndarray,
    ) -> None:
        """Execute cold_nodes serially. Each node's output feeds the next."""
        job_id = self._new_job_id()
        self._active_job_id = job_id

        def step(idx: int, current_input: np.ndarray) -> None:
            if self._active_job_id != job_id:
                return
            if idx >= len(cold_nodes):
                self.tapReady.emit(job_id, current_input)
                self._active_job_id = None
                return
            node = cold_nodes[idx]
            chain_hash = pipeline.chain_hash_for(node.node_id, volume.version)
            chain_det = pipeline.deterministic_through(node.node_id)

            def on_ready(_section_job_id: int, arr: np.ndarray) -> None:
                if self._active_job_id != job_id:
                    return
                try:
                    self._orch.sectionReady.disconnect(on_ready)
                    self._orch.failed.disconnect(on_failed)
                except (TypeError, RuntimeError):
                    pass
                self._active_on_ready = None
                self._active_on_failed = None
                self.intermediateReady.emit(job_id, node.node_id, arr)
                step(idx + 1, arr)

            def on_failed(_section_job_id: int, message: str) -> None:
                if self._active_job_id != job_id:
                    return
                try:
                    self._orch.sectionReady.disconnect(on_ready)
                    self._orch.failed.disconnect(on_failed)
                except (TypeError, RuntimeError):
                    pass
                self._active_on_ready = None
                self._active_on_failed = None
                self._active_job_id = None
                self.failed.emit(job_id, f"{node.spec.name}: {message}")

            self.progress.emit(idx + 1, len(cold_nodes), node.spec.name)
            self._active_on_ready = on_ready
            self._active_on_failed = on_failed
            self._orch.sectionReady.connect(on_ready)
            self._orch.failed.connect(on_failed)
            self._orch.request(
                node.spec, node.params, volume, axis, index,
                input_section=current_input, chain_hash=chain_hash,
                skip_cache_write=not chain_det,
            )

        step(0, starting_input)

    def _read_raw(self, volume: SeismicVolume, axis: Axis, index: int) -> np.ndarray:
        if axis is Axis.INLINE:
            return volume.read_inline(index)
        if axis is Axis.XLINE:
            return volume.read_xline(index)
        return volume.read_timeslice(index)
