"""GUI-side compute orchestrator. Owns thread pool, cache, debounce timer."""

from __future__ import annotations

import os

import numpy as np
from pydantic import BaseModel
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from eggseis.axes import Axis
from eggseis.compute.cache import SectionLRU, make_cache_key
from eggseis.compute.job import Job
from eggseis.compute.tile import split_section
from eggseis.compute.worker import TileRunnable, TileSignals
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec
from eggseis.plugin_runner import make_trace_context

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
        *,
        input_section: np.ndarray | None = None,
        chain_hash: str | None = None,
        skip_cache_write: bool = False,
    ) -> None:
        axis_enum = Axis(axis)
        self._pending = {
            "spec": spec,
            "params": params,
            "volume": volume,
            "axis": axis_enum,
            "index": index,
            "input_section": None if input_section is None else input_section.copy(),
            "chain_hash": chain_hash,
            "skip_cache_write": skip_cache_write,
        }
        key = make_cache_key(spec, params, volume, axis_enum, index, chain_hash=chain_hash)
        self._pending["key"] = key
        # Cache reads use spec.deterministic alone; chain-poisoned entries
        # were never written, so a miss is the only possible outcome.
        # Cache-hit fast path: skip debounce, cancel any in-flight job
        # (a late tilesReady/sectionReady would clobber this synchronous
        # paint), and emit immediately.
        if spec.deterministic:
            cached = self._cache.get(key)
            if cached is not None:
                self._pending = None
                self.cancel_active()
                self.sectionReady.emit(Job().id, cached)
                return
        self._debounce.start()

    def cancel_active(self) -> None:
        if self._active is not None:
            self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self._delivered_ranges.clear()
        self._tiles_remaining = 0

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
            override = req["input_section"]
            ts = override if override is not None else volume.read_timeslice(index)
            self.sectionReady.emit(Job().id, ts)
            return

        if req["input_section"] is not None:
            section = req["input_section"]
        else:
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
            context=make_trace_context(volume, axis, index),
            cache_key=req.get("key"),
            skip_cache_write=req.get("skip_cache_write", False),
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
        if job.spec.deterministic and not job.skip_cache_write:
            self._cache.put(job.cache_key, job.output)
        self.sectionReady.emit(job.id, job.output)
        self._active = None

    def _on_tile_failed(self, job_id: int, message: str) -> None:
        if self._active is None or self._active.id != job_id:
            return
        self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self._delivered_ranges.clear()
        self._tiles_remaining = 0
        self.failed.emit(job_id, message)

    def _flush_delivery(self) -> None:
        job = self._active
        if job is None or job.token.cancelled or not self._delivered_ranges:
            return
        ranges = list(self._delivered_ranges)
        self._delivered_ranges.clear()
        self.tilesReady.emit(job.id, job.output, ranges)
