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
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.pipeline.model import SOURCE_ID, Pipeline


class PipelineExecutor(QObject):
    tapReady = Signal(int, object)               # job_id, ndarray
    intermediateReady = Signal(int, str, object)  # job_id, node_id, ndarray
    failed = Signal(int, str)                     # job_id, message

    def __init__(self, orchestrator: JobOrchestrator) -> None:
        super().__init__()
        self._orch = orchestrator
        self._next_job_id = 0

    def _new_job_id(self) -> int:
        self._next_job_id += 1
        return self._next_job_id

    def request_tap(
        self,
        pipeline: Pipeline,
        volume: SeismicVolume,
        axis: Axis | str,
        index: int,
    ) -> None:
        axis_enum = Axis(axis) if not isinstance(axis, Axis) else axis
        plan = pipeline.nodes_up_to_tap()

        # Source tap or empty plan: synchronous raw read.
        if not plan or pipeline.tap_node_id == SOURCE_ID:
            raw = self._read_raw(volume, axis_enum, index)
            self.tapReady.emit(self._new_job_id(), raw)
            return

        # TODO Task 12+: cold-suffix execution.
        raise NotImplementedError

    def _read_raw(self, volume: SeismicVolume, axis: Axis, index: int) -> np.ndarray:
        if axis is Axis.INLINE:
            return volume.read_inline(index)
        if axis is Axis.XLINE:
            return volume.read_xline(index)
        return volume.read_timeslice(index)
