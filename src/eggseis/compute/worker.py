"""Single-tile QRunnable worker. Calls compute_tile, emits completed/failed."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from eggseis.compute.job import Job
from eggseis.compute.tile import Tile
from eggseis.plugin_runner import compute_tile


class TileSignals(QObject):
    """QObject host for cross-thread signals. One instance shared per orchestrator."""

    completed = Signal(int, int, int)   # job_id, tile.start, tile.stop
    failed = Signal(int, str)           # job_id, repr(exc)


class TileRunnable(QRunnable):
    def __init__(self, job: Job, tile: Tile, signals: TileSignals) -> None:
        super().__init__()
        self._job = job
        self._tile = tile
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # type: ignore[override]
        job = self._job
        if job.token.cancelled:
            return
        try:
            params_dump = job.params.model_dump()
            if job.spec.vectorized:
                compute_tile(
                    job.spec, params_dump, job.context,
                    start=self._tile.start, stop=self._tile.stop, out=job.output,
                    inputs=job.inputs,
                )
            else:
                for i in range(self._tile.start, self._tile.stop):
                    if job.token.cancelled:
                        return
                    compute_tile(
                        job.spec, params_dump, job.context,
                        start=i, stop=i + 1, out=job.output,
                        inputs=job.inputs,
                    )

            if not job.token.cancelled:
                self._signals.completed.emit(
                    job.id, self._tile.start, self._tile.stop
                )
        except Exception as exc:
            self._signals.failed.emit(job.id, repr(exc))
