"""GUI-side compute orchestrator. Owns thread pool, cache, debounce timer."""

from __future__ import annotations

import os

import numpy as np  # noqa: F401  — used in Tasks 8/9
from pydantic import BaseModel
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from eggseis.axes import Axis
from eggseis.compute.cache import CacheKey, SectionLRU, params_hash
from eggseis.compute.job import Job
from eggseis.compute.tile import split_section  # noqa: F401  — used in Task 8
from eggseis.compute.worker import TileRunnable, TileSignals  # noqa: F401 — used in Task 8
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec

DEBOUNCE_MS = 150
DELIVERY_MS = 50
TILE_SIZE = 64


class JobOrchestrator(QObject):
    """Single point of contact between the GUI and the compute layer."""

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
        # Filled in Task 8.
        if self._pending is None:
            return

    def _on_tile_completed(self, job_id: int, start: int, stop: int) -> None:
        # Filled in Tasks 8+9.
        return

    def _on_tile_failed(self, job_id: int, message: str) -> None:
        # Filled in Task 12.
        return

    def _flush_delivery(self) -> None:
        # Filled in Task 9.
        return
