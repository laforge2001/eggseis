"""In-memory LRU cache for fully-computed section arrays."""

from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np

DEFAULT_BUDGET = int(os.environ.get("EGGSEIS_CACHE_BYTES", 500_000_000))


def params_hash(params_dump: dict[str, Any]) -> str:
    """Stable 16-byte hex digest of a parameter dict.

    Canonical-JSON encoding (sorted keys, no whitespace) means two equal dicts
    always hash the same regardless of insertion order.  Also used as the leaf
    contribution when computing a single-node `chain_hash`.
    """
    blob = json.dumps(params_dump, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    plugin_id: str
    plugin_version: str
    chain_hash: str
    axis: str
    index: int
    volume_version: tuple


def make_cache_key(spec, params, volume, axis, index, *, chain_hash: str | None = None) -> CacheKey:
    """Build a `CacheKey` for a `(spec, params, volume, axis, index)` tuple.

    Single source of truth shared by `JobOrchestrator` and tests so the
    canonical layout never drifts. `axis` may be an `Axis` enum or its
    `.value` string.

    Pass an explicit `chain_hash` when the caller has already folded upstream
    cache keys and params into a combined digest (e.g. `PipelineExecutor`).
    Omit it for single-node callers; the hash is derived from `params` alone.
    """
    axis_value = axis.value if hasattr(axis, "value") else axis
    return CacheKey(
        plugin_id=spec.id,
        plugin_version=spec.version,
        chain_hash=chain_hash if chain_hash is not None else params_hash(params.model_dump()),
        axis=axis_value,
        index=index,
        volume_version=volume.version,
    )


class SectionLRU:
    """OrderedDict-backed LRU keyed on `CacheKey`, byte-budgeted."""

    def __init__(self, byte_budget: int = DEFAULT_BUDGET) -> None:
        self._budget = byte_budget
        self._items: OrderedDict[CacheKey, np.ndarray] = OrderedDict()
        self._bytes = 0

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: CacheKey) -> np.ndarray | None:
        arr = self._items.get(key)
        if arr is None:
            return None
        self._items.move_to_end(key)
        return arr

    def put(self, key: CacheKey, arr: np.ndarray) -> None:
        if key in self._items:
            self._bytes -= self._items[key].nbytes
            del self._items[key]
        if arr.nbytes > self._budget:
            return
        self._items[key] = arr
        self._bytes += arr.nbytes
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while self._bytes > self._budget and self._items:
            _, evicted = self._items.popitem(last=False)
            self._bytes -= evicted.nbytes
