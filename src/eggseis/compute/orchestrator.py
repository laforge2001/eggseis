"""GUI-side compute orchestrator. Owns thread pool, cache, debounce timer."""

from __future__ import annotations

import os

import numpy as np
from pydantic import BaseModel
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from eggseis.axes import Axis
from eggseis.compute.cache import CacheKey, SectionLRU, params_hash
from eggseis.compute.job import Job
from eggseis.compute.tile import split_section
from eggseis.compute.worker import TileRunnable, TileSignals
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec

DEBOUNCE_MS = 150
DELIVERY_MS = 50
TILE_SIZE = 64


class JobOrchestrator(QObject):
    """Single point of contact between the GUI and the compute layer.

    Signal contract:
    - `tilesReady(job_id, output_buffer, ranges)` fires every ~50 ms while a
      job runs, carrying the current `job.output` and the list of
      `(start, stop)` tile ranges newly written since the previous emission.
      Consumers paint partial results.
    - `sectionReady(job_id, array)` fires once when the job completes (or
      on a synchronous cache hit / timeslice short-circuit). Consumers
      treat this as the final, authoritative paint.
    - On the last tile of a normal compute, `tilesReady` may fire
      back-to-back with `sectionReady` carrying the same buffer; viewers
      should be idempotent across that pair.
    """

    sectionReady = Signal(int, object)
    tilesReady = Signal(int, object, object)
    failed = Signal(int, str)

    def __init__(self, cache: SectionLRU | None = None) -> None:
        super().__init__()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, (os.cpu_count() or 2) - 1))
        self._cache = cache or SectionLRU()
        self._signals = TileSignals()
        self._signals.completed.connect(self._on_tile_completed)
        self._signals.failed.connect(self._on_tile_failed)

        self._pending: dict | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._dispatch_pending)

        self._delivery = QTimer(self)
        self._delivery.setInterval(DELIVERY_MS)
        self._delivery.timeout.connect(self._flush_delivery)

        self._active: Job | None = None
        self._tiles_remaining: int = 0
        self._delivered_ranges: list[tuple[int, int]] = []

    @property
    def cache(self) -> SectionLRU:
        return self._cache

    def request(
        self,
        spec: PluginSpec,
        params: BaseModel,
        volume: SeismicVolume,
        axis: Axis | str,
        index: int,
    ) -> None:
        self._pending = {
            "spec": spec,
            "params": params,
            "volume": volume,
            "axis": Axis(axis),
            "index": index,
        }
        # Cache-hit fast path: skip debounce.
        key = self._make_key(spec, params, volume, Axis(axis), index)
        if spec.deterministic:
            cached = self._cache.get(key)
            if cached is not None:
                self._pending = None
                self.sectionReady.emit(Job().id, cached)
                return
        self._debounce.start()

    def cancel_active(self) -> None:
        if self._active is not None:
            self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self._delivered_ranges.clear()

    def _make_key(
        self,
        spec: PluginSpec,
        params: BaseModel,
        volume: SeismicVolume,
        axis: Axis,
        index: int,
    ) -> CacheKey:
        return CacheKey(
            plugin_id=spec.id,
            plugin_version=spec.version,
            params_hash=params_hash(params.model_dump()),
            axis=axis.value,
            index=index,
            volume_version=volume.version,
        )

    def _dispatch_pending(self) -> None:
        if self._pending is None:
            return
        req = self._pending
        self._pending = None
        spec: PluginSpec = req["spec"]
        params: BaseModel = req["params"]
        volume: SeismicVolume = req["volume"]
        axis: Axis = req["axis"]
        index: int = req["index"]

        if axis is Axis.TIMESLICE:
            # Trace-local attributes don't apply; surface raw and stop.
            self.sectionReady.emit(Job().id, volume.read_timeslice(index))
            return

        section = (
            volume.read_inline(index) if axis is Axis.INLINE else volume.read_xline(index)
        )

        if self._active is not None:
            self._active.token.cancel()

        job = Job(
            spec=spec,
            params=params,
            volume=volume,
            axis=axis,
            index=index,
            section=section,
            output=np.empty_like(section, dtype=np.float32),
            context={
                "sample_rate_ms": volume.geometry.sample_rate_ms,
                "axis": axis.value,
                "index": index,
            },
        )
        self._active = job
        tiles = split_section(section.shape[0], TILE_SIZE)
        self._tiles_remaining = len(tiles)
        self._delivered_ranges.clear()
        self._delivery.start()
        for tile in tiles:
            self._pool.start(TileRunnable(job, tile, self._signals))

    def _on_tile_completed(self, job_id: int, start: int, stop: int) -> None:
        job = self._active
        if job is None or job.id != job_id or job.token.cancelled:
            return
        self._delivered_ranges.append((start, stop))
        self._tiles_remaining -= 1
        if self._tiles_remaining == 0:
            self._finalize(job)

    def _finalize(self, job: Job) -> None:
        self._delivery.stop()
        if self._delivered_ranges:
            self.tilesReady.emit(job.id, job.output, list(self._delivered_ranges))
            self._delivered_ranges.clear()
        if job.spec.deterministic:
            self._cache.put(
                self._make_key(job.spec, job.params, job.volume, job.axis, job.index),
                job.output,
            )
        self.sectionReady.emit(job.id, job.output)
        self._active = None

    def _on_tile_failed(self, job_id: int, message: str) -> None:
        # Filled in Task 12.
        return

    def _flush_delivery(self) -> None:
        # Filled in Task 9.
        return
