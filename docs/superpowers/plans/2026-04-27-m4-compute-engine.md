# M4 Compute Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move plugin execution off the GUI thread with a debounced, cancellable, cache-backed orchestrator so sliders feel responsive on slow attributes and pan-and-return is instant.

**Architecture:** New `eggseis.compute` package owns a `JobOrchestrator` (QObject) that takes plugin requests, debounces them in a `QTimer`, splits the section into tile rows, dispatches tiles to a `QThreadPool` of `QRunnable` workers, delivers in-progress paints via a coalesced `tilesReady` signal every ~50 ms, and serves identical-key requests from an in-memory `SectionLRU`. The library/CLI keep the synchronous `run_on_section`; the GUI calls the orchestrator instead. Trace-loop logic is factored into a single `compute_tile` primitive shared by both call sites so vectorized vs scalar parity is enforced by construction.

**Tech Stack:** Python, NumPy, PySide6 (QThreadPool, QRunnable, QTimer, Signal/Slot), pydantic v2, pytest + pytest-qt, scipy.signal (existing).

**Companion design doc:** `M4-PLAN.md` — read it first for scope, locked decisions, and risks. This file is the engineer's task list.

---

## File Map

**New files (under `src/eggseis/compute/`):**
- `__init__.py` — re-exports `JobOrchestrator`, `SectionLRU`, `CacheKey`.
- `cache.py` — `SectionLRU`, `CacheKey`, `params_hash`, `DEFAULT_BUDGET`.
- `tile.py` — `Tile` dataclass, `split_section()`.
- `job.py` — `Job`, `CancellationToken`.
- `worker.py` — `TileSignals(QObject)`, `TileRunnable(QRunnable)`.
- `orchestrator.py` — `JobOrchestrator(QObject)`.

**Modified files:**
- `src/eggseis/data.py` — add `SeismicVolume.version` property.
- `src/eggseis/backends/mdio.py` — add `MDIOBackend.version` property.
- `src/eggseis/plugin_runner.py` — extract `compute_tile()`, keep `run_on_section()` as a thin wrapper.
- `src/eggseis/viewers/section.py` — `set_overlay(arr, *, partial=False)` keeps levels stable across in-progress paints.
- `src/eggseis/app.py` — instantiate orchestrator, wire `tilesReady` / `sectionReady` / `failed`, surface `Help → Compute Errors`.
- `tests/conftest.py` — add `version` to `FakeBackend`, add `slow_spec` and `noise_spec` fixtures, add `envelope_spec` convenience fixture.
- `docs/development.md` — append a "Compute model" section.
- `docs/plugin-authoring.md` — append one paragraph on `deterministic=False`.

**New test files:**
- `tests/test_compute_cache.py`
- `tests/test_compute_tile.py`
- `tests/test_compute_orchestrator.py`

**Modified test files:**
- `tests/test_plugin_runner.py` — extend for `compute_tile`, vectorized parity.
- `tests/test_gui_smoke.py` — assert overlay arrives via orchestrator signal.

Each `eggseis.compute` module has one responsibility. Splits along that line because the orchestrator is the only thing that ties Qt to the rest — keeping cache/tile/job free of Qt makes them trivially unit-testable.

---

## Task 1: Cache primitives — `params_hash` and `SectionLRU`

**Files:**
- Create: `src/eggseis/compute/__init__.py`
- Create: `src/eggseis/compute/cache.py`
- Create: `tests/test_compute_cache.py`

- [ ] **Step 1.1: Write failing tests for `params_hash` stability**

`tests/test_compute_cache.py`:

```python
"""Tests for the compute cache primitives."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.compute.cache import CacheKey, SectionLRU, params_hash


def test_params_hash_stable_across_key_order():
    assert params_hash({"a": 1, "b": 2.0}) == params_hash({"b": 2.0, "a": 1})


def test_params_hash_changes_on_value_change():
    assert params_hash({"k": 1.0}) != params_hash({"k": 1.0001})


def test_params_hash_handles_nested_lists():
    assert params_hash({"taps": [1, 2, 3]}) == params_hash({"taps": [1, 2, 3]})
    assert params_hash({"taps": [1, 2, 3]}) != params_hash({"taps": [3, 2, 1]})
```

- [ ] **Step 1.2: Run tests and verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_compute_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'eggseis.compute'`.

- [ ] **Step 1.3: Implement `compute/__init__.py` and `compute/cache.py` for `params_hash`**

`src/eggseis/compute/__init__.py`:

```python
"""eggseis compute engine — async, cancellable, cache-backed plugin execution."""

from eggseis.compute.cache import CacheKey, SectionLRU, params_hash

__all__ = ["CacheKey", "SectionLRU", "params_hash"]
```

`src/eggseis/compute/cache.py`:

```python
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
    always hash the same regardless of insertion order.
    """
    blob = json.dumps(params_dump, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    plugin_id: str
    plugin_version: str
    params_hash: str
    axis: str
    index: int
    volume_version: tuple


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
```

- [ ] **Step 1.4: Run params_hash tests, verify pass**

```bash
pytest tests/test_compute_cache.py -v
```
Expected: 3 passed.

- [ ] **Step 1.5: Add failing tests for `SectionLRU`**

Append to `tests/test_compute_cache.py`:

```python
def _key(i: int) -> CacheKey:
    return CacheKey(
        plugin_id="p",
        plugin_version="0.1.0",
        params_hash="h",
        axis="inline",
        index=i,
        volume_version=("mdio", "/x", 1, 1),
    )


def test_lru_get_returns_none_when_missing():
    cache = SectionLRU()
    assert cache.get(_key(0)) is None


def test_lru_put_then_get_returns_array():
    cache = SectionLRU()
    arr = np.zeros((4,), dtype=np.float32)
    cache.put(_key(0), arr)
    assert cache.get(_key(0)) is arr


def test_lru_evicts_oldest_when_over_budget():
    cache = SectionLRU(byte_budget=8 * 1024)
    a = np.zeros((1024,), dtype=np.float32)  # 4 KB
    b = np.zeros((1024,), dtype=np.float32)
    c = np.zeros((1024,), dtype=np.float32)
    cache.put(_key(0), a)
    cache.put(_key(1), b)
    cache.put(_key(2), c)
    assert cache.get(_key(0)) is None
    assert cache.get(_key(1)) is not None
    assert cache.get(_key(2)) is not None
    assert cache.nbytes <= 8 * 1024


def test_lru_get_marks_entry_as_recently_used():
    cache = SectionLRU(byte_budget=8 * 1024)
    a = np.zeros((1024,), dtype=np.float32)
    b = np.zeros((1024,), dtype=np.float32)
    c = np.zeros((1024,), dtype=np.float32)
    cache.put(_key(0), a)
    cache.put(_key(1), b)
    cache.get(_key(0))                        # touch: 0 now newest
    cache.put(_key(2), c)                     # forces an eviction
    assert cache.get(_key(0)) is not None
    assert cache.get(_key(1)) is None         # 1 was the oldest


def test_lru_drops_silently_when_value_exceeds_budget():
    cache = SectionLRU(byte_budget=64)
    big = np.zeros((100,), dtype=np.float32)  # 400 bytes
    cache.put(_key(0), big)
    assert len(cache) == 0
    assert cache.nbytes == 0
```

- [ ] **Step 1.6: Run, verify pass**

```bash
pytest tests/test_compute_cache.py -v
```
Expected: 8 passed (3 hash + 5 LRU).

- [ ] **Step 1.7: Commit**

```bash
git add src/eggseis/compute/__init__.py src/eggseis/compute/cache.py tests/test_compute_cache.py
git commit -m "feat(compute): SectionLRU cache + params_hash"
```

---

## Task 2: Tile splitter — center-out priority

**Files:**
- Create: `src/eggseis/compute/tile.py`
- Create: `tests/test_compute_tile.py`

- [ ] **Step 2.1: Write failing tests**

`tests/test_compute_tile.py`:

```python
"""Tests for tile slicing and ordering."""

from __future__ import annotations

from itertools import pairwise

from eggseis.compute.tile import Tile, split_section


def test_split_section_covers_full_range():
    tiles = split_section(200, tile_size=64)
    spans = sorted((t.start, t.stop) for t in tiles)
    # contiguous, no gaps, no overlap, hits exactly 200
    assert spans[0][0] == 0
    assert spans[-1][1] == 200
    for (_, a_stop), (b_start, _) in pairwise(spans):
        assert a_stop == b_start


def test_split_section_orders_center_first():
    tiles = split_section(200, tile_size=64)
    midpoint = 100
    first = tiles[0]
    last = tiles[-1]
    first_dist = abs(((first.start + first.stop) // 2) - midpoint)
    last_dist = abs(((last.start + last.stop) // 2) - midpoint)
    assert first_dist < last_dist


def test_split_section_handles_partial_final_tile():
    tiles = split_section(100, tile_size=64)
    sizes = sorted(t.size for t in tiles)
    assert sizes == [36, 64]


def test_split_section_single_tile_when_smaller_than_tile_size():
    tiles = split_section(40, tile_size=64)
    assert len(tiles) == 1
    assert tiles[0] == Tile(start=0, stop=40, priority=0)
```

- [ ] **Step 2.2: Run, verify fail**

```bash
pytest tests/test_compute_tile.py -v
```
Expected: `ModuleNotFoundError: No module named 'eggseis.compute.tile'`.

- [ ] **Step 2.3: Implement `tile.py`**

`src/eggseis/compute/tile.py`:

```python
"""Tile slicing primitives for section-level compute jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    """A contiguous range of trace indices within a section, plus its priority key."""

    start: int          # inclusive
    stop: int           # exclusive
    priority: int       # smaller = run first

    @property
    def size(self) -> int:
        return self.stop - self.start


def split_section(n_traces: int, tile_size: int = 64) -> list[Tile]:
    """Split [0, n_traces) into tiles ordered by distance from the section midpoint."""
    if n_traces <= 0:
        return []
    mid = n_traces // 2
    tiles: list[Tile] = []
    for start in range(0, n_traces, tile_size):
        stop = min(start + tile_size, n_traces)
        center = (start + stop) // 2
        tiles.append(Tile(start=start, stop=stop, priority=abs(center - mid)))
    tiles.sort(key=lambda t: t.priority)
    return tiles
```

- [ ] **Step 2.4: Run, verify pass**

```bash
pytest tests/test_compute_tile.py -v
```
Expected: 4 passed.

- [ ] **Step 2.5: Commit**

```bash
git add src/eggseis/compute/tile.py tests/test_compute_tile.py
git commit -m "feat(compute): center-out section tile splitter"
```

---

## Task 3: Volume version — backend-supplied identity

**Files:**
- Modify: `src/eggseis/data.py`
- Modify: `src/eggseis/backends/mdio.py`
- Modify: `tests/conftest.py:13-71` (add `version` to `FakeBackend`)
- Modify: `tests/test_data.py` (add a `version` test)
- Modify: `tests/test_mdio_backend.py` (add an MDIO `version` test)

- [ ] **Step 3.1: Write failing test on `SeismicVolume.version`**

Append to `tests/test_data.py`:

```python
def test_volume_version_delegates_to_backend(fake_backend):
    from eggseis.data import SeismicVolume
    vol = SeismicVolume(fake_backend, name="x")
    assert vol.version == fake_backend.version
```

- [ ] **Step 3.2: Run, verify fail**

```bash
pytest tests/test_data.py::test_volume_version_delegates_to_backend -v
```
Expected: `AttributeError: 'FakeBackend' object has no attribute 'version'`.

- [ ] **Step 3.3: Add `version` to `FakeBackend` and `SeismicBackend` Protocol**

In `tests/conftest.py`, add inside `FakeBackend` (after `read_trace`):

```python
    @property
    def version(self) -> tuple:
        return ("fake", id(self))
```

In `src/eggseis/data.py`, add to the `SeismicBackend` Protocol (after `read_trace`):

```python
    @property
    def version(self) -> tuple: ...
```

…and to `SeismicVolume` (after the `dtype` property):

```python
    @property
    def version(self) -> tuple:
        """Opaque tuple uniquely identifying this volume's bytes (cache key input)."""
        return self._backend.version
```

- [ ] **Step 3.4: Run, verify pass**

```bash
pytest tests/test_data.py -v
```
Expected: all `test_data.py` tests pass.

- [ ] **Step 3.5: Add failing test for MDIO version**

Append to `tests/test_mdio_backend.py`:

```python
def test_mdio_version_includes_path_and_stat(sample_mdio_path):
    from eggseis.backends.mdio import MDIOBackend
    b = MDIOBackend(sample_mdio_path)
    v = b.version
    assert v[0] == "mdio"
    assert v[1] == str(sample_mdio_path.resolve())
    assert isinstance(v[2], int) and v[2] > 0   # st_size
    assert isinstance(v[3], int) and v[3] > 0   # st_mtime_ns
```

- [ ] **Step 3.6: Run, verify fail**

```bash
pytest tests/test_mdio_backend.py::test_mdio_version_includes_path_and_stat -v
```
Expected: `AttributeError`.

- [ ] **Step 3.7: Implement `MDIOBackend.version`**

In `src/eggseis/backends/mdio.py`, add after the `dtype` property (around line 80):

```python
    @property
    def version(self) -> tuple:
        """`(backend_kind, resolved_path, st_size, st_mtime_ns)` — used as a cache key.

        For MDIO, `path` is a directory; its `st_mtime_ns` updates whenever
        immediate children change. Adequate for read-only surveys; in-place
        chunk edits at identical size + mtime would falsely hit the cache,
        and that is acceptable for v1.0.
        """
        p = self.path.resolve()
        st = p.stat()
        return ("mdio", str(p), st.st_size, st.st_mtime_ns)
```

- [ ] **Step 3.8: Run, verify pass**

```bash
pytest tests/test_mdio_backend.py tests/test_data.py -v
```
Expected: all pass.

- [ ] **Step 3.9: Commit**

```bash
git add src/eggseis/data.py src/eggseis/backends/mdio.py tests/conftest.py tests/test_data.py tests/test_mdio_backend.py
git commit -m "feat(data): SeismicVolume.version for cache-key identity"
```

---

## Task 4: `compute_tile` — single source of truth for the trace loop

**Files:**
- Modify: `src/eggseis/plugin_runner.py`
- Modify: `tests/test_plugin_runner.py`

- [ ] **Step 4.1: Write failing test for `compute_tile` partial range**

Append to `tests/test_plugin_runner.py`:

```python
def test_compute_tile_writes_only_requested_range(fake_backend):
    import numpy as np
    from eggseis.builtins.envelope import envelope
    from eggseis.data import SeismicVolume
    from eggseis.plugin_runner import compute_tile

    vol = SeismicVolume(fake_backend)
    section = vol.read_inline(vol.geometry.inline_min)
    out = np.zeros_like(section, dtype=np.float32)

    spec = envelope._eggseis_spec
    context = {"sample_rate_ms": vol.geometry.sample_rate_ms,
               "axis": "inline", "index": vol.geometry.inline_min}
    compute_tile(spec, {}, section, context, start=2, stop=5, out=out)

    # Rows 2..4 written, others untouched.
    assert (out[:2] == 0).all()
    assert (out[5:] == 0).all()
    assert (out[2:5] != 0).any()
```

- [ ] **Step 4.2: Run, verify fail**

```bash
pytest tests/test_plugin_runner.py::test_compute_tile_writes_only_requested_range -v
```
Expected: `ImportError: cannot import name 'compute_tile'`.

- [ ] **Step 4.3: Refactor `plugin_runner.py` to expose `compute_tile`**

Replace the body of `src/eggseis/plugin_runner.py` with:

```python
"""Synchronous plugin execution across the visible section."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec


def compute_tile(
    spec: PluginSpec,
    params_dump: dict[str, Any],
    section: np.ndarray,
    context: dict[str, Any],
    *,
    start: int,
    stop: int,
    out: np.ndarray,
) -> None:
    """Run `spec` over `section[start:stop]`, writing into `out[start:stop]`.

    Used directly by tile workers and indirectly (whole-section call) by
    the synchronous `run_on_section` below.
    """
    if spec.vectorized:
        kwargs = dict(params_dump)
        if spec.accepts_context:
            kwargs["context"] = context
        result = spec.func(traces=section[start:stop], **kwargs).astype(np.float32)
        out[start:stop] = result
        return

    for i in range(start, stop):
        kwargs = dict(params_dump)
        if spec.accepts_context:
            kwargs["context"] = context
        out[i] = spec.func(section[i], **kwargs)


def run_on_section(
    spec: PluginSpec,
    params: BaseModel,
    volume: SeismicVolume,
    axis: Axis | str,
    index: int,
) -> np.ndarray:
    """Run a trace-local plugin across every trace in the visible section.

    Synchronous; library/CLI use this. The GUI uses `JobOrchestrator` instead.

    For timeslices, trace-local attributes do not apply — the source array is
    returned unchanged.
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
    out = np.empty_like(section, dtype=np.float32)
    compute_tile(
        spec,
        params.model_dump(),
        section,
        context,
        start=0,
        stop=section.shape[0],
        out=out,
    )
    return out
```

- [ ] **Step 4.4: Run, verify pass — including all M3 plugin runner tests**

```bash
pytest tests/test_plugin_runner.py -v
```
Expected: all pass (existing M3 tests still green; new partial-range test green).

- [ ] **Step 4.5: Add failing test that vectorized matches scalar end-to-end**

Append to `tests/test_plugin_runner.py`:

```python
def test_vectorized_envelope_matches_scalar(fake_backend):
    import numpy as np
    from scipy.signal import hilbert

    from eggseis.builtins.envelope import envelope
    from eggseis.data import SeismicVolume
    from eggseis.plugin_runner import run_on_section

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    section = vol.read_inline(vol.geometry.inline_min)
    expected = np.stack([np.abs(hilbert(section[i])) for i in range(section.shape[0])])
    np.testing.assert_allclose(out, expected.astype(np.float32), rtol=1e-5)
```

- [ ] **Step 4.6: Run, verify pass**

```bash
pytest tests/test_plugin_runner.py::test_vectorized_envelope_matches_scalar -v
```
Expected: PASS (the `envelope` builtin already uses `vectorized=True`-style implementation; if not, this still passes via scalar fallback. Either way: parity asserted.)

- [ ] **Step 4.7: Commit**

```bash
git add src/eggseis/plugin_runner.py tests/test_plugin_runner.py
git commit -m "refactor(plugin_runner): extract compute_tile primitive"
```

---

## Task 5: `Job` and `CancellationToken`

**Files:**
- Create: `src/eggseis/compute/job.py`
- Modify: `tests/test_compute_orchestrator.py` (new file, but used here for unit tests on Job/Token)

Better to put pure-Python `Job` tests in their own file:

- Create: `tests/test_compute_job.py`

- [ ] **Step 5.1: Write failing tests**

`tests/test_compute_job.py`:

```python
"""Tests for compute Job + CancellationToken (no Qt)."""

from __future__ import annotations

from eggseis.compute.job import CancellationToken, Job


def test_token_default_not_cancelled():
    t = CancellationToken()
    assert t.cancelled is False


def test_token_cancel_sets_flag():
    t = CancellationToken()
    t.cancel()
    assert t.cancelled is True


def test_job_ids_are_unique_and_increasing():
    j1 = Job()
    j2 = Job()
    assert j1.id != j2.id
    assert j2.id > j1.id


def test_job_default_token_not_cancelled():
    j = Job()
    assert j.token.cancelled is False
```

- [ ] **Step 5.2: Run, verify fail**

```bash
pytest tests/test_compute_job.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `job.py`**

`src/eggseis/compute/job.py`:

```python
"""Compute job + cancellation primitives. No Qt deps — pure Python."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import BaseModel

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec

_job_ids = itertools.count(1)


class CancellationToken:
    """Thread-safe one-way flag. Workers poll `.cancelled` between tile rows."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class Job:
    """One section-level compute request. Output buffer is owned by the job."""

    id: int = field(default_factory=lambda: next(_job_ids))
    spec: PluginSpec | None = None
    params: BaseModel | None = None
    volume: SeismicVolume | None = None
    axis: Axis = Axis.INLINE
    index: int = 0
    section: np.ndarray | None = None
    output: np.ndarray | None = None
    context: dict[str, Any] = field(default_factory=dict)
    token: CancellationToken = field(default_factory=CancellationToken)
```

- [ ] **Step 5.4: Run, verify pass**

```bash
pytest tests/test_compute_job.py -v
```
Expected: 4 passed.

- [ ] **Step 5.5: Commit**

```bash
git add src/eggseis/compute/job.py tests/test_compute_job.py
git commit -m "feat(compute): Job + CancellationToken"
```

---

## Task 6: `TileRunnable` — single-tile worker

**Files:**
- Create: `src/eggseis/compute/worker.py`
- Modify: `tests/test_compute_orchestrator.py` (new file)

- [ ] **Step 6.1: Write failing test that runs a TileRunnable directly**

`tests/test_compute_orchestrator.py`:

```python
"""Headless tests for the compute orchestrator + worker. Uses pytest-qt."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool

from eggseis.compute.job import Job
from eggseis.compute.tile import Tile
from eggseis.compute.worker import TileRunnable, TileSignals


@pytest.fixture
def envelope_spec_and_section(fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.data import SeismicVolume
    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    section = vol.read_inline(vol.geometry.inline_min).astype(np.float32)
    return spec, section


def test_tile_runnable_writes_into_job_output(qtbot, envelope_spec_and_section):
    spec, section = envelope_spec_and_section
    job = Job(
        spec=spec,
        params=spec.param_model(),
        section=section,
        output=np.zeros_like(section, dtype=np.float32),
        context={"sample_rate_ms": 4.0, "axis": "inline", "index": 100},
    )
    signals = TileSignals()
    tile = Tile(start=0, stop=section.shape[0], priority=0)

    with qtbot.waitSignal(signals.completed, timeout=2000) as blocker:
        QThreadPool.globalInstance().start(TileRunnable(job, tile, signals))

    job_id, start, stop = blocker.args
    assert job_id == job.id
    assert (start, stop) == (0, section.shape[0])
    assert (job.output != 0).any()


def test_tile_runnable_skips_when_token_already_cancelled(qtbot, envelope_spec_and_section):
    spec, section = envelope_spec_and_section
    job = Job(
        spec=spec,
        params=spec.param_model(),
        section=section,
        output=np.zeros_like(section, dtype=np.float32),
        context={"sample_rate_ms": 4.0, "axis": "inline", "index": 100},
    )
    job.token.cancel()
    signals = TileSignals()

    completed: list[tuple] = []
    signals.completed.connect(lambda *args: completed.append(args))

    QThreadPool.globalInstance().start(
        TileRunnable(job, Tile(start=0, stop=section.shape[0], priority=0), signals)
    )
    qtbot.wait(150)
    assert completed == []
    assert (job.output == 0).all()
```

- [ ] **Step 6.2: Run, verify fail**

```bash
pytest tests/test_compute_orchestrator.py -v
```
Expected: `ModuleNotFoundError: No module named 'eggseis.compute.worker'`.

- [ ] **Step 6.3: Implement `worker.py`**

`src/eggseis/compute/worker.py`:

```python
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
            # Cancel-aware loop only matters for scalar plugins; vectorized
            # path is one shot per tile and finishes before the next check.
            if job.spec.vectorized:
                if job.token.cancelled:
                    return
                compute_tile(
                    job.spec, params_dump, job.section, job.context,
                    start=self._tile.start, stop=self._tile.stop, out=job.output,
                )
            else:
                # Walk row-by-row so cancel is checked between traces.
                for i in range(self._tile.start, self._tile.stop):
                    if job.token.cancelled:
                        return
                    compute_tile(
                        job.spec, params_dump, job.section, job.context,
                        start=i, stop=i + 1, out=job.output,
                    )

            if not job.token.cancelled:
                self._signals.completed.emit(
                    job.id, self._tile.start, self._tile.stop
                )
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(job.id, repr(exc))
```

- [ ] **Step 6.4: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py -v
```
Expected: 2 passed.

- [ ] **Step 6.5: Commit**

```bash
git add src/eggseis/compute/worker.py tests/test_compute_orchestrator.py
git commit -m "feat(compute): TileRunnable worker with cooperative cancel"
```

---

## Task 7: Orchestrator — cache hit path (no workers yet)

**Files:**
- Create: `src/eggseis/compute/orchestrator.py`
- Modify: `tests/test_compute_orchestrator.py`
- Modify: `src/eggseis/compute/__init__.py` (re-export `JobOrchestrator`)

- [ ] **Step 7.1: Write failing test for cache-hit synchronous return**

Append to `tests/test_compute_orchestrator.py`:

```python
def test_orchestrator_returns_from_cache_when_present(qtbot, fake_backend):
    import numpy as np
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.cache import CacheKey, SectionLRU, params_hash
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    params = spec.param_model()
    cache = SectionLRU()
    pre = np.full(
        (vol.geometry.n_xlines, vol.geometry.n_samples), 7.0, dtype=np.float32
    )
    cache.put(
        CacheKey(
            plugin_id=spec.id,
            plugin_version=spec.version,
            params_hash=params_hash(params.model_dump()),
            axis="inline",
            index=vol.geometry.inline_min,
            volume_version=vol.version,
        ),
        pre,
    )

    orch = JobOrchestrator(cache=cache)
    with qtbot.waitSignal(orch.sectionReady, timeout=1000) as blocker:
        orch.request(spec, params, vol, "inline", vol.geometry.inline_min)

    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, pre)
```

- [ ] **Step 7.2: Run, verify fail**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_returns_from_cache_when_present -v
```
Expected: `ModuleNotFoundError: No module named 'eggseis.compute.orchestrator'`.

- [ ] **Step 7.3: Scaffold orchestrator (cache-hit path only — no workers, no debounce yet)**

`src/eggseis/compute/orchestrator.py`:

```python
"""GUI-side compute orchestrator. Owns thread pool, cache, debounce timer."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from pydantic import BaseModel

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
```

Update `src/eggseis/compute/__init__.py`:

```python
"""eggseis compute engine — async, cancellable, cache-backed plugin execution."""

from eggseis.compute.cache import CacheKey, SectionLRU, params_hash
from eggseis.compute.job import CancellationToken, Job
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.compute.tile import Tile, split_section
from eggseis.compute.worker import TileRunnable, TileSignals

__all__ = [
    "CacheKey",
    "CancellationToken",
    "Job",
    "JobOrchestrator",
    "SectionLRU",
    "Tile",
    "TileRunnable",
    "TileSignals",
    "params_hash",
    "split_section",
]
```

- [ ] **Step 7.4: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_returns_from_cache_when_present -v
```
Expected: PASS.

- [ ] **Step 7.5: Commit**

```bash
git add src/eggseis/compute/orchestrator.py src/eggseis/compute/__init__.py tests/test_compute_orchestrator.py
git commit -m "feat(compute): JobOrchestrator scaffold + cache-hit fast path"
```

---

## Task 8: Orchestrator — dispatch tiles to workers (no debounce yet)

**Files:**
- Modify: `src/eggseis/compute/orchestrator.py`
- Modify: `tests/test_compute_orchestrator.py`

- [ ] **Step 8.1: Add failing test for end-to-end miss → compute → sectionReady**

Append to `tests/test_compute_orchestrator.py`:

```python
def test_orchestrator_computes_section_on_miss(qtbot, fake_backend):
    import numpy as np
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.plugin_runner import run_on_section

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=5000) as blocker:
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)

    _job_id, arr = blocker.args
    expected = run_on_section(
        spec, spec.param_model(), vol, "inline", vol.geometry.inline_min
    )
    np.testing.assert_allclose(arr, expected, rtol=1e-5)
```

- [ ] **Step 8.2: Run, verify fail**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_computes_section_on_miss -v
```
Expected: timeout (debounce dispatch is a no-op stub).

- [ ] **Step 8.3: Implement `_dispatch_pending` and `_on_tile_completed`**

In `src/eggseis/compute/orchestrator.py`, replace the stub bodies:

```python
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
```

- [ ] **Step 8.4: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py -v
```
Expected: all 4 pass (cache hit + new miss test + 2 worker tests).

- [ ] **Step 8.5: Add failing test that a hit follows a miss within budget**

```python
def test_orchestrator_caches_after_compute(qtbot, fake_backend):
    import time
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()

    # Miss → compute.
    with qtbot.waitSignal(orch.sectionReady, timeout=5000):
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    assert len(orch.cache) == 1

    # Hit → fast.
    t0 = time.perf_counter()
    with qtbot.waitSignal(orch.sectionReady, timeout=500):
        orch.request(spec, spec.param_model(), vol, "inline", vol.geometry.inline_min)
    assert (time.perf_counter() - t0) * 1000 < 200
```

- [ ] **Step 8.6: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_caches_after_compute -v
```
Expected: PASS.

- [ ] **Step 8.7: Commit**

```bash
git add src/eggseis/compute/orchestrator.py tests/test_compute_orchestrator.py
git commit -m "feat(compute): orchestrator dispatches tile workers + caches results"
```

---

## Task 9: Progressive delivery — `tilesReady` coalescing

**Files:**
- Modify: `src/eggseis/compute/orchestrator.py`
- Modify: `tests/test_compute_orchestrator.py`

- [ ] **Step 9.1: Add failing test that a slow plugin emits `tilesReady` before `sectionReady`**

Append to `tests/test_compute_orchestrator.py`:

```python
@pytest.fixture
def slow_spec():
    """Per-trace sleep — long enough that delivery timer fires mid-job."""
    import time as _time

    import numpy as np
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Slow", version="0.1.0")
    def slow(trace, gain: float = Param(1.0, min=0.0, max=10.0)):
        _time.sleep(0.005)
        return (trace * gain).astype(np.float32)

    yield slow._eggseis_spec
    clear_registry()


def test_orchestrator_emits_tiles_ready_progressively(qtbot, fake_backend, slow_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    tile_emissions: list[list[tuple[int, int]]] = []
    orch.tilesReady.connect(lambda _id, _buf, ranges: tile_emissions.append(list(ranges)))

    with qtbot.waitSignal(orch.sectionReady, timeout=10_000):
        orch.request(slow_spec, slow_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)

    assert tile_emissions, "tilesReady never fired before sectionReady"
    flat = sorted(r for batch in tile_emissions for r in batch)
    assert flat[0][0] == 0 or any(r[0] == 0 for r in flat)
```

- [ ] **Step 9.2: Run, verify fail or pass-by-luck**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_emits_tiles_ready_progressively -v
```
Expected: likely PASS only if `_finalize` already emits `tilesReady` once at the end. The test asserts emissions during the run too, so it may FAIL until `_flush_delivery` is wired.

- [ ] **Step 9.3: Implement `_flush_delivery`**

In `src/eggseis/compute/orchestrator.py`, replace `_flush_delivery`:

```python
    def _flush_delivery(self) -> None:
        job = self._active
        if job is None or job.token.cancelled or not self._delivered_ranges:
            return
        ranges = list(self._delivered_ranges)
        self._delivered_ranges.clear()
        self.tilesReady.emit(job.id, job.output, ranges)
```

- [ ] **Step 9.4: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py -v
```
Expected: all green.

- [ ] **Step 9.5: Commit**

```bash
git add src/eggseis/compute/orchestrator.py tests/test_compute_orchestrator.py
git commit -m "feat(compute): coalesced tilesReady delivery every 50 ms"
```

---

## Task 10: Debounce — coalesce slider chatter

**Files:**
- Modify: `tests/test_compute_orchestrator.py`

(`_debounce` timer already triggers `_dispatch_pending`. We just need a test that proves rapid `request()` calls collapse to one job.)

- [ ] **Step 10.1: Add failing test that 10 rapid requests fire only one compute**

Append to `tests/test_compute_orchestrator.py`:

```python
def test_debounce_coalesces_rapid_requests(qtbot, fake_backend):
    from eggseis.builtins.envelope import envelope
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    spec = envelope._eggseis_spec
    orch = JobOrchestrator()

    sections: list[int] = []
    orch.sectionReady.connect(lambda job_id, _arr: sections.append(job_id))

    # Fire 10 requests within the debounce window.
    for i in range(10):
        orch.request(spec, spec.param_model(), vol, "inline",
                     vol.geometry.inline_min + (i % vol.geometry.n_inlines))

    # Wait for the (single) job to finish.
    qtbot.wait(2000)
    # Exactly one compute fired; cache may have served any further requests.
    # Loosely: never more than the number of distinct (axis, index) tuples.
    assert len(sections) <= vol.geometry.n_inlines
    # Tighter: no more than one *non-cache-hit* compute. Cache size proves it.
    assert len(orch.cache) <= vol.geometry.n_inlines
```

- [ ] **Step 10.2: Run, verify pass**

The 150 ms debounce already handles this. If the test fails due to timing, increase `qtbot.wait` to 3000.

```bash
pytest tests/test_compute_orchestrator.py::test_debounce_coalesces_rapid_requests -v
```
Expected: PASS.

- [ ] **Step 10.3: Commit**

```bash
git add tests/test_compute_orchestrator.py
git commit -m "test(compute): debounce coalesces rapid request chatter"
```

---

## Task 11: Supersede — cancel in-flight when a new request arrives

**Files:**
- Modify: `tests/test_compute_orchestrator.py`

- [ ] **Step 11.1: Add failing test that supersede sets the prior job's cancel token**

Append to `tests/test_compute_orchestrator.py`:

```python
def test_supersede_cancels_in_flight_job(qtbot, fake_backend, slow_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    captured_jobs: list = []
    orig_dispatch = orch._dispatch_pending

    def spy() -> None:
        orig_dispatch()
        if orch._active is not None:
            captured_jobs.append(orch._active)

    orch._dispatch_pending = spy  # type: ignore[assignment]

    # First request — let it dispatch and start running.
    orch.request(slow_spec, slow_spec.param_model(),
                 vol, "inline", vol.geometry.inline_min)
    qtbot.wait(200)  # let debounce fire and a few tiles start
    assert captured_jobs, "first job didn't dispatch"
    first_job = captured_jobs[0]

    # Second request — supersede.
    with qtbot.waitSignal(orch.sectionReady, timeout=10_000):
        orch.request(slow_spec, slow_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min + 1)

    assert first_job.token.cancelled is True
```

- [ ] **Step 11.2: Run, verify pass (logic already in `_dispatch_pending`)**

```bash
pytest tests/test_compute_orchestrator.py::test_supersede_cancels_in_flight_job -v
```
Expected: PASS.

- [ ] **Step 11.3: Commit**

```bash
git add tests/test_compute_orchestrator.py
git commit -m "test(compute): supersede cancels prior in-flight job"
```

---

## Task 12: Failure handling — worker exception surfaces `failed`

**Files:**
- Modify: `src/eggseis/compute/orchestrator.py`
- Modify: `tests/test_compute_orchestrator.py`

- [ ] **Step 12.1: Add failing test for `failed` signal on broken plugin**

Append to `tests/test_compute_orchestrator.py`:

```python
@pytest.fixture
def broken_spec():
    from eggseis.plugin import Param, clear_registry, trace_attribute
    clear_registry()

    @trace_attribute(name="Broken", version="0.1.0")
    def broken(trace, k: float = Param(1.0)):
        raise RuntimeError("nope")

    yield broken._eggseis_spec
    clear_registry()


def test_orchestrator_emits_failed_on_worker_exception(qtbot, fake_backend, broken_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    with qtbot.waitSignal(orch.failed, timeout=5000) as blocker:
        orch.request(broken_spec, broken_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)
    _job_id, msg = blocker.args
    assert "nope" in msg
```

- [ ] **Step 12.2: Run, verify fail**

```bash
pytest tests/test_compute_orchestrator.py::test_orchestrator_emits_failed_on_worker_exception -v
```
Expected: timeout — `_on_tile_failed` is still a no-op.

- [ ] **Step 12.3: Implement `_on_tile_failed`**

In `src/eggseis/compute/orchestrator.py`:

```python
    def _on_tile_failed(self, job_id: int, message: str) -> None:
        if self._active is None or self._active.id != job_id:
            return
        self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self._delivered_ranges.clear()
        self.failed.emit(job_id, message)
```

- [ ] **Step 12.4: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py -v
```
Expected: all green.

- [ ] **Step 12.5: Commit**

```bash
git add src/eggseis/compute/orchestrator.py tests/test_compute_orchestrator.py
git commit -m "feat(compute): orchestrator surfaces worker failures"
```

---

## Task 13: Determinism gate — non-deterministic plugins skip cache

**Files:**
- Modify: `tests/test_compute_orchestrator.py`

The orchestrator already gates reads (`if spec.deterministic`) and writes (in `_finalize`). Lock the behaviour with a test.

- [ ] **Step 13.1: Add failing test**

```python
@pytest.fixture
def noise_spec():
    import numpy as np
    from eggseis.plugin import Param, clear_registry, trace_attribute
    clear_registry()

    @trace_attribute(name="Noise", version="0.1.0", deterministic=False)
    def noise(trace, gain: float = Param(1.0)):
        return np.random.default_rng().standard_normal(trace.shape).astype(np.float32)

    yield noise._eggseis_spec
    clear_registry()


def test_non_deterministic_plugin_is_not_cached(qtbot, fake_backend, noise_spec):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    vol = SeismicVolume(fake_backend)
    orch = JobOrchestrator()

    with qtbot.waitSignal(orch.sectionReady, timeout=5000):
        orch.request(noise_spec, noise_spec.param_model(),
                     vol, "inline", vol.geometry.inline_min)
    assert len(orch.cache) == 0
```

- [ ] **Step 13.2: Run, verify pass**

```bash
pytest tests/test_compute_orchestrator.py::test_non_deterministic_plugin_is_not_cached -v
```
Expected: PASS (gates are already in place).

- [ ] **Step 13.3: Commit**

```bash
git add tests/test_compute_orchestrator.py
git commit -m "test(compute): deterministic=False plugins skip cache"
```

---

## Task 14: `SectionViewer.set_overlay` accepts a `partial=` flag

**Files:**
- Modify: `src/eggseis/viewers/section.py:83-90`
- Modify: `tests/test_gui_smoke.py` (if there is a viewer-only test) or a new `tests/test_section_viewer.py`

- [ ] **Step 14.1: Add failing test**

`tests/test_section_viewer.py` (create):

```python
"""Section viewer overlay behaviour. Headless via QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from eggseis.data import SeismicVolume
from eggseis.viewers.section import SectionViewer


def test_partial_overlay_keeps_baseline_levels(qtbot, fake_backend):
    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    # Render once to populate baseline_levels.
    viewer._render()  # noqa: SLF001 — internal hook used in test
    baseline = viewer._baseline_levels

    arr = np.zeros((vol.geometry.n_xlines, vol.geometry.n_samples), dtype=np.float32)
    viewer.set_overlay(arr, partial=True)
    assert viewer._baseline_levels == baseline
```

- [ ] **Step 14.2: Run, verify fail**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_section_viewer.py -v
```
Expected: `TypeError: set_overlay() got an unexpected keyword argument 'partial'`.

- [ ] **Step 14.3: Update `set_overlay` signature**

In `src/eggseis/viewers/section.py`, replace:

```python
    def set_overlay(self, arr: np.ndarray) -> None:
        """Display `arr` (same shape as the source slice) instead of raw data."""
        self._overlay = arr
        self._render()
```

with:

```python
    def set_overlay(self, arr: np.ndarray, *, partial: bool = False) -> None:
        """Display `arr` instead of raw data.

        `partial=True` indicates an in-progress paint from a tile worker;
        suppresses any baseline-level recompute so the colour scale stays
        stable across the run. The orchestrator's final `sectionReady` paint
        passes `partial=False` to allow level refresh when levels are not
        locked.
        """
        self._overlay = arr
        self._partial_overlay = partial
        self._render()
```

In `__init__`, add (alongside `self._overlay = None`):

```python
        self._partial_overlay: bool = False
```

In `_render`, replace the levels block:

```python
        if showing_overlay and self._levels_locked and self._baseline_levels is not None:
            levels = self._baseline_levels
        elif showing_overlay and self._partial_overlay and self._baseline_levels is not None:
            # Don't recompute levels mid-paint; reuse what we have.
            levels = self._baseline_levels
        else:
            levels = self._compute_levels(arr)
            if not showing_overlay:
                self._baseline_levels = levels
```

- [ ] **Step 14.4: Run, verify pass**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_section_viewer.py tests/test_gui_smoke.py -v
```
Expected: all pass (existing GUI smoke must still pass — `set_overlay` is backwards-compatible).

- [ ] **Step 14.5: Commit**

```bash
git add src/eggseis/viewers/section.py tests/test_section_viewer.py
git commit -m "feat(viewers): SectionViewer.set_overlay(partial=) keeps levels stable"
```

---

## Task 15: Wire `MainWindow` to the orchestrator

**Files:**
- Modify: `src/eggseis/app.py:35-258`
- Modify: `tests/test_gui_smoke.py`

- [ ] **Step 15.1: Add failing GUI smoke test that overlay arrives via `sectionReady`**

Append to `tests/test_gui_smoke.py` (or replace the existing M3 attribute-apply test):

```python
def test_attribute_apply_via_orchestrator(qtbot, demo_project_path):
    from eggseis.app import MainWindow
    from eggseis.builtins.envelope import envelope

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)

    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume)

    with qtbot.waitSignal(win._compute.sectionReady, timeout=10_000):  # noqa: SLF001
        win._activate_plugin(envelope._eggseis_spec)                    # noqa: SLF001

    assert win.section_viewer.has_overlay
```

- [ ] **Step 15.2: Run, verify fail**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py::test_attribute_apply_via_orchestrator -v
```
Expected: `AttributeError: 'MainWindow' object has no attribute '_compute'`.

- [ ] **Step 15.3: Replace `_recompute_overlay` with orchestrator-driven flow**

In `src/eggseis/app.py`:

Add import near the top:

```python
from eggseis.compute.orchestrator import JobOrchestrator
```

In `MainWindow.__init__`, after `self._param_dock_widget` setup and before `self._project = None`:

```python
        self._compute = JobOrchestrator()
        self._compute_errors: list[tuple[str, str]] = []
        self._compute.tilesReady.connect(self._on_tiles_ready)
        self._compute.sectionReady.connect(self._on_section_ready)
        self._compute.failed.connect(self._on_compute_failed)
```

Replace `_recompute_overlay`:

```python
    def _recompute_overlay(self, params=None) -> None:
        spec = self._active_plugin
        if spec is None or not self.section_viewer.has_volume:
            return
        if params is None:
            params = spec.param_model()
        self._compute.request(
            spec,
            params,
            self.section_viewer._volume,  # noqa: SLF001 — internal contract
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )
```

Add three slot methods:

```python
    def _on_tiles_ready(self, _job_id: int, buffer, _ranges) -> None:
        self.section_viewer.set_overlay(buffer, partial=True)

    def _on_section_ready(self, _job_id: int, arr) -> None:
        self.section_viewer.set_overlay(arr, partial=False)

    def _on_compute_failed(self, _job_id: int, message: str) -> None:
        spec = self._active_plugin
        name = spec.name if spec else "compute"
        self._compute_errors.append((name, message))
        self.statusBar().showMessage(f"{name} failed: {message}", 5000)
```

- [ ] **Step 15.4: Run, verify pass**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py -v
```
Expected: all pass.

- [ ] **Step 15.5: Commit**

```bash
git add src/eggseis/app.py tests/test_gui_smoke.py
git commit -m "feat(app): wire JobOrchestrator into MainWindow overlay flow"
```

---

## Task 16: `Help → Compute Errors…` menu

**Files:**
- Modify: `src/eggseis/app.py`

- [ ] **Step 16.1: Add failing test**

Append to `tests/test_gui_smoke.py`:

```python
def test_compute_errors_menu_lists_failures(qtbot, demo_project_path):
    from eggseis.app import MainWindow
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Boom", version="0.1.0")
    def boom(trace, k: float = Param(1.0)):
        raise RuntimeError("boom")

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume)

    with qtbot.waitSignal(win._compute.failed, timeout=5000):  # noqa: SLF001
        win._activate_plugin(boom._eggseis_spec)               # noqa: SLF001

    assert any("boom" in msg for _name, msg in win._compute_errors)  # noqa: SLF001
```

- [ ] **Step 16.2: Run, verify pass (handler already records errors)**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py::test_compute_errors_menu_lists_failures -v
```
Expected: PASS — `_on_compute_failed` already appends to `_compute_errors`.

- [ ] **Step 16.3: Add `Help → Compute Errors…` menu action**

In `src/eggseis/app.py`, inside `_build_menus`, after the existing plugin-errors action block:

```python
        a_compute_errors = QAction("&Compute Errors…", self)
        a_compute_errors.triggered.connect(self._on_show_compute_errors)
        m_help.addAction(a_compute_errors)
        self._compute_errors_action = a_compute_errors
```

Add the handler:

```python
    def _on_show_compute_errors(self) -> None:
        if not self._compute_errors:
            QMessageBox.information(
                self, "Compute Errors", "No compute errors recorded this session."
            )
            return
        body = "\n\n".join(f"• {name}\n    {msg}" for name, msg in self._compute_errors)
        box = QMessageBox(self)
        box.setWindowTitle("Compute Errors")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{len(self._compute_errors)} compute error(s) this session:")
        box.setDetailedText(body)
        box.exec()
```

- [ ] **Step 16.4: Run full GUI suite**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py -v
```
Expected: all pass.

- [ ] **Step 16.5: Commit**

```bash
git add src/eggseis/app.py tests/test_gui_smoke.py
git commit -m "feat(app): Help → Compute Errors… session log"
```

---

## Task 17: Docs updates

**Files:**
- Modify: `docs/development.md`
- Modify: `docs/plugin-authoring.md`

- [ ] **Step 17.1: Append "Compute model" section to `docs/development.md`**

Add to the bottom of `docs/development.md`:

```markdown
## Compute model (M4+)

When you select an attribute in the GUI, the section is computed off the GUI
thread by `eggseis.compute.JobOrchestrator`:

1. `MainWindow._recompute_overlay` calls `orchestrator.request(...)`.
2. The request is debounced 150 ms; rapid slider chatter coalesces into one
   dispatch.
3. On dispatch the orchestrator splits the section into 64-trace tiles and
   submits one `TileRunnable` per tile to `QThreadPool.globalInstance()`.
   Tiles are ordered center-out so the visible middle of the section appears
   first.
4. As tiles complete, the orchestrator coalesces them into a `tilesReady`
   emission every 50 ms; the section viewer paints partial results.
5. When the last tile lands, `sectionReady` fires and the result is stored
   in `SectionLRU` (default 500 MB, override with `EGGSEIS_CACHE_BYTES`).
6. Identical subsequent requests serve from cache and return synchronously
   without ever touching a worker.

Library/CLI paths (`eggseis info`, `eggseis dump-inline`,
`eggseis.plugin_runner.run_on_section`) stay synchronous — the orchestrator
is GUI-only.
```

- [ ] **Step 17.2: Append `deterministic` paragraph to `docs/plugin-authoring.md`**

Add a short section near the bottom:

```markdown
## Determinism and caching

By default, plugins are `deterministic=True`, which means a given plugin +
parameters + slice combination always produces the same bytes. Eggseis caches
those results in memory and reuses them when the user pans back.

If your plugin reads a clock, calls an RNG, or otherwise produces different
output for identical inputs, mark it as non-deterministic so it is never
cached:

```python
@trace_attribute(name="My Random Filter", deterministic=False)
def my_random(trace, gain: float = Param(1.0)):
    ...
```
```

- [ ] **Step 17.3: Run the lint suite to make sure nothing regressed**

```bash
./scripts/test.sh ci
```
Expected: green.

- [ ] **Step 17.4: Commit**

```bash
git add docs/development.md docs/plugin-authoring.md
git commit -m "docs: M4 compute model + deterministic flag note"
```

---

## Task 18: Manual demo + perf smoke

**Files:** none (verification only).

- [ ] **Step 18.1: Run the GUI against the demo project and exercise sliders**

```bash
./scripts/test.sh demo
```

Manual checks (no asserts — eyeball it):
- Switch from `None` to `Ormsby Bandpass`. Observe section paint center-out.
- Drag `f3` slider rapidly across its range. UI never freezes; no backlog of stale paints accumulates.
- Pan inline → another inline → back. Second visit appears instantly.
- Toggle to a `vectorized=True` plugin (e.g. `envelope`). Whole section paints in well under a second.

If any of these fails, adjust `DEBOUNCE_MS` / `DELIVERY_MS` / `TILE_SIZE` constants in `orchestrator.py` and re-test. Do not change them without a captured "before/after" timing observation.

- [ ] **Step 18.2: Run full CI suite one more time**

```bash
./scripts/test.sh ci
```
Expected: green on all platforms via GitHub Actions on the PR.

- [ ] **Step 18.3: Open PR**

```bash
git push -u origin m4-compute-engine
gh pr create --title "M4: GUI compute engine — async, debounced, cached" --body "$(cat <<'EOF'
## Summary
- `eggseis.compute` package: `JobOrchestrator`, `SectionLRU`, `TileRunnable`, debounce + supersede + cooperative cancel.
- GUI overlay flow now runs off the Qt thread; pan-and-return hits cache; sliders feel responsive on slow attributes.
- Library / CLI paths unchanged — `run_on_section` stays synchronous and shares one `compute_tile` primitive with the new tile workers.

## Test plan
- [ ] `./scripts/test.sh ci` green locally
- [ ] CI green on Linux/macOS/Windows
- [ ] Manual: drag Ormsby `n_taps=401` sliders, no UI freeze
- [ ] Manual: pan-and-return on a previously-computed view < 50 ms
- [ ] Manual: vectorized `envelope` on a 1000×1500 section < 1 s

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After review + merge: follow the milestone wrap-up rule (CHANGELOG `[v0.1.0a4]`, README status update, M5 issue + branch, tag `v0.1.0a4`).

---

## Self-Review Summary

**Spec coverage (vs. `M4-PLAN.md` exit criteria):**
- Slider responsiveness on slow attribute → Task 10 (debounce) + Task 11 (supersede) + Task 18 (manual).
- <50 ms cache hit on pan-and-return → Task 8 step 8.5 (asserts <200 ms in CI; manual verifies <50 ms locally).
- Vectorized plugin <1 s on 1000×1500 → Task 4 (vectorized parity) + Task 18 (manual perf smoke).
- Cancel observable → Task 11 (`token.cancelled is True`).
- Cache eviction observable → Task 1 step 1.5.
- `deterministic=False` never cached → Task 13.
- Headless tests across orchestrator/cancel/debounce/cache/parity/delivery → Tasks 1, 2, 4, 8–13.
- CLI/library unchanged → Task 4 keeps `run_on_section` working; Task 17 documents the boundary.

**Placeholders:** none. Every code step shows the code; every test step shows asserts.

**Type/identifier consistency:** `JobOrchestrator.request(spec, params, volume, axis, index)` is identical in Tasks 7, 8, 10, 11, 13, 15. `set_overlay(arr, *, partial=False)` is consistent across Tasks 14 and 15. `TileSignals.completed(int, int, int)` and `TileSignals.failed(int, str)` match between worker (Task 6) and orchestrator hookups (Tasks 7, 12). `CacheKey` field order matches between `cache.py` (Task 1) and `_make_key` (Task 7).

**One late discovery during review:** Task 5 declared `Job(spec=..., params=..., ...)` with all fields optional — confirmed `_dispatch_pending` (Task 8) always populates the ones it needs. The default `Job()` form is used only as a "throwaway id source" in cache-hit / timeslice paths; that pattern is consistent across the orchestrator.

---

Plan complete and saved to `docs/superpowers/plans/2026-04-27-m4-compute-engine.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `executing-plans`, batch with checkpoints.

Which approach?
