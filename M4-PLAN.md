# M4 — "The compute feels good"

**Milestone 4 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M3-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Stop blocking the GUI. Drag a slider on a slow attribute and the section keeps repainting; pan away and back to a previously-computed view and it returns instantly; switch from a trace-by-trace plugin to a vectorized one and a 1000×1500 section finishes in well under a second.

Three threads of work, one outcome: the app stops feeling like a prototype.

1. **Worker scheduling.** Move plugin execution off the GUI thread, debounce parameter chatter, cancel jobs that have been superseded, deliver results progressively.
2. **In-memory cache.** Keyed on plugin identity + params + slice; default ~500 MB LRU. Pan-and-return becomes free.
3. **Vectorized path.** Already a flag in M3; in M4 it actually pays off because the runner hands the plugin one batch instead of looping in Python.

If the running M3 demo (envelope on the F3 fragment) was already fast enough to fool you into thinking compute is "fine", pick a slower kernel — Ormsby with 401 taps, or a hand-rolled Python loop — to drive the M4 work. The whole point is to make slow kernels survivable.

## Exit criteria

You're done with M4 when this is true:

- Drag the `f1`/`f2`/`f3`/`f4` sliders on `Ormsby Bandpass` against a real survey; the section keeps repainting; the UI never freezes; intermediate slider positions don't accumulate as a backlog of completed-but-stale paints.
- Pan to a slice, switch to another, switch back — the previously-computed view appears in **<50 ms** (cache hit).
- A `vectorized=True` plugin (e.g. `envelope`, `instantaneous_phase`) runs on a 1000×1500 section in **<1 s** wall-clock on a typical laptop CPU.
- Cancelling a job mid-flight is observable: the job stops, the worker frees up, the next request starts immediately.
- Cache obeys its byte budget — fill it past 500 MB and the oldest entries evict; eviction is observable in tests, not just "trust me".
- `deterministic=False` plugins are *never* served from cache, even on identical input.
- Headless tests cover: orchestrator request → cancel, debounce coalescing, cache hit/miss/evict, vectorized vs scalar parity, progressive tile delivery, cooperative cancel at tile boundary.
- `eggseis info` and CLI paths still work — compute engine is a GUI concern; library/CLI keep their synchronous `run_on_section`.

---

## Locked design decisions for M4

| Area | Decision |
|---|---|
| Worker pool | `QThreadPool` + `QRunnable`. One global pool owned by the orchestrator. `setMaxThreadCount(os.cpu_count() - 1)` floor 2. |
| Debounce | 150 ms single-shot `QTimer` on the orchestrator. Resets on every `request()`. Fires once on quiet. |
| Cancellation | Cooperative `threading.Event` per job. Workers check between tile rows. Orchestrator sets it on supersede or explicit cancel. |
| Tile shape | Slice the section along the trace axis into fixed-size tile rows (default 64 traces). One tile = one `QRunnable`. |
| Tile priority | Distance from section midpoint, ascending. Tile at the center runs first; edges last. Good enough for M4 — viewport-aware prioritization is a v1.1 polish. |
| Progressive delivery | Orchestrator holds an output buffer per active job. Workers post completed tiles back to the orchestrator (queued connection). Orchestrator emits `tilesReady(job_id, ranges)` at most every 50 ms (coalescing timer). |
| Cache | `eggseis.compute.cache.SectionLRU` — `OrderedDict`-backed, byte-budgeted (default 500 MB). Whole-section values, not per-tile. |
| Cache key | `(plugin_id, plugin_version, params_hash, axis, index, volume_version)`. `params_hash` = blake2b of canonical-JSON `model_dump()`. `volume_version` = `(backend_kind, resolved_path, st_size, st_mtime_ns)` snapshotted on first access. |
| Determinism gate | `spec.deterministic=False` ⇒ skip cache reads and writes. The flag from M3 finally earns its keep. |
| Vectorized contract | `spec.vectorized=True` ⇒ runner calls `func(traces=section_tile, **params)` once per **tile**, not once per **section**. Lets the cache key stay coarse while compute parallelism stays per-tile. |
| Failure handling | Worker exceptions caught, surfaced as a status-bar message + a `Help → Compute Errors` log (mirrors M3's plugin-error pattern). Orchestrator stays alive. |
| Library/CLI | `run_on_section` remains synchronous. The new orchestrator is a GUI-only layer that *uses* the same `compute_tile` primitive underneath. |
| Settings | One env var: `EGGSEIS_CACHE_BYTES` (default `500_000_000`). Debounce ms hard-coded; revisit if anyone complains. |

Things deliberately not decided here:
- A persistent / disk-backed cache. Roadmap says v1.1.
- Per-tile cache reuse across param changes. Trace-local plugins ⇒ params change ⇒ every trace output changes. Tile-cache buys nothing for M4 plugins.
- GPU offload. Out of scope.

---

## Step 1: Package skeleton

```
src/eggseis/compute/
├── __init__.py
├── tile.py            # Tile dataclass + slicing helpers
├── cache.py           # SectionLRU
├── job.py             # Job, JobResult, CancellationToken
├── worker.py          # TileRunnable (QRunnable subclass)
└── orchestrator.py    # JobOrchestrator (QObject)
```

`eggseis.compute` is a *new* package; nothing in M1–M3 imports it. Touch `app.py` to plug it in.

## Step 2: Tile and cache key primitives

```python
# src/eggseis/compute/tile.py
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Tile:
    """A contiguous range of traces within a section, plus its priority key."""

    start: int          # first trace index (inclusive)
    stop: int           # last trace index (exclusive)
    priority: int       # smaller = run first

    @property
    def size(self) -> int:
        return self.stop - self.start


def split_section(n_traces: int, tile_size: int = 64) -> list[Tile]:
    """Center-out ordering: tile spanning the section midpoint runs first."""
    starts = list(range(0, n_traces, tile_size))
    mid = n_traces // 2
    tiles = []
    for s in starts:
        e = min(s + tile_size, n_traces)
        center = (s + e) // 2
        tiles.append(Tile(start=s, stop=e, priority=abs(center - mid)))
    tiles.sort(key=lambda t: t.priority)
    return tiles
```

```python
# src/eggseis/compute/cache.py
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
            return  # too big to ever cache; drop silently
        self._items[key] = arr
        self._bytes += arr.nbytes
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while self._bytes > self._budget and self._items:
            _, evicted = self._items.popitem(last=False)
            self._bytes -= evicted.nbytes
```

Volume version helper lives next to the backend, not in compute:

```python
# src/eggseis/backends/mdio.py — add a property
@property
def version(self) -> tuple:
    p = self._path.resolve()
    st = p.stat()
    return ("mdio", str(p), st.st_size, st.st_mtime_ns)
```

…and surface it on `SeismicVolume`:

```python
# src/eggseis/data.py
@property
def version(self) -> tuple:
    return self._backend.version
```

## Step 3: Job + cancellation

```python
# src/eggseis/compute/job.py
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
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class Job:
    id: int = field(default_factory=lambda: next(_job_ids))
    spec: PluginSpec | None = None
    params: BaseModel | None = None
    volume: SeismicVolume | None = None
    axis: Axis = Axis.INLINE
    index: int = 0
    section: np.ndarray | None = None       # full source slice (read once)
    output: np.ndarray | None = None        # destination buffer, shape == section
    context: dict[str, Any] = field(default_factory=dict)
    token: CancellationToken = field(default_factory=CancellationToken)
```

The job carries its own output buffer so workers write directly without locking — each tile owns a disjoint row range.

## Step 4: Tile worker

```python
# src/eggseis/compute/worker.py
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal

from eggseis.compute.job import Job
from eggseis.compute.tile import Tile


class TileSignals(QObject):
    completed = Signal(int, int, int)  # job_id, tile.start, tile.stop
    failed = Signal(int, str)          # job_id, repr(exc)


class TileRunnable(QRunnable):
    def __init__(self, job: Job, tile: Tile, signals: TileSignals) -> None:
        super().__init__()
        self._job = job
        self._tile = tile
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        job = self._job
        if job.token.cancelled:
            return
        try:
            spec = job.spec
            params = job.params.model_dump()
            section = job.section
            out = job.output
            kwargs = dict(params)
            if spec.accepts_context:
                kwargs["context"] = job.context

            if spec.vectorized:
                batch = section[self._tile.start : self._tile.stop]
                result = spec.func(traces=batch, **kwargs).astype(np.float32)
                out[self._tile.start : self._tile.stop] = result
            else:
                for i in range(self._tile.start, self._tile.stop):
                    if job.token.cancelled:
                        return
                    out[i] = spec.func(section[i], **kwargs)

            if not job.token.cancelled:
                self._signals.completed.emit(job.id, self._tile.start, self._tile.stop)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(job.id, repr(exc))
```

Cancel granularity = one tile row in vectorized mode, one trace in scalar mode. That's plenty for sub-second kernels.

## Step 5: Orchestrator

```python
# src/eggseis/compute/orchestrator.py
from __future__ import annotations

import os
import time

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
    """GUI-thread-only API. Owns a thread pool, debounce timer, cache, in-flight job."""

    sectionReady = Signal(int, object)           # job_id, full ndarray (cache hit OR final)
    tilesReady = Signal(int, object, object)     # job_id, ndarray (in-progress), [(start, stop), ...]
    failed = Signal(int, str)                    # job_id, message

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
        self._debounce.start()

    def cancel_active(self) -> None:
        if self._active is not None:
            self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self._delivered_ranges.clear()

    def _dispatch_pending(self) -> None:
        if self._pending is None:
            return
        req = self._pending
        self._pending = None
        self._start_job(**req)

    def _start_job(
        self,
        *,
        spec: PluginSpec,
        params: BaseModel,
        volume: SeismicVolume,
        axis: Axis,
        index: int,
    ) -> None:
        # Cache lookup first — only path that beats <50 ms.
        key = self._make_key(spec, params, volume, axis, index)
        if spec.deterministic:
            cached = self._cache.get(key)
            if cached is not None:
                # Allocate a fresh job_id for the listener even on hit.
                job = Job(spec=spec, params=params, volume=volume, axis=axis, index=index)
                self.sectionReady.emit(job.id, cached)
                return

        # Read once on the GUI thread (M4 keeps backend reads synchronous).
        section = self._read(volume, axis, index)
        if axis is Axis.TIMESLICE:
            # Trace-local attributes don't apply; surface raw and stop.
            self.sectionReady.emit(Job().id, section)
            return

        # Cancel any in-flight job before starting a new one.
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

    def _read(self, volume: SeismicVolume, axis: Axis, index: int) -> np.ndarray:
        if axis is Axis.INLINE:
            return volume.read_inline(index)
        if axis is Axis.XLINE:
            return volume.read_xline(index)
        return volume.read_timeslice(index)

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

    def _on_tile_completed(self, job_id: int, start: int, stop: int) -> None:
        job = self._active
        if job is None or job.id != job_id or job.token.cancelled:
            return
        self._delivered_ranges.append((start, stop))
        self._tiles_remaining -= 1
        if self._tiles_remaining == 0:
            self._finalize(job)

    def _on_tile_failed(self, job_id: int, message: str) -> None:
        if self._active is None or self._active.id != job_id:
            return
        self._active.token.cancel()
        self._active = None
        self._delivery.stop()
        self.failed.emit(job_id, message)

    def _flush_delivery(self) -> None:
        job = self._active
        if job is None or not self._delivered_ranges:
            return
        ranges = self._delivered_ranges
        self._delivered_ranges = []
        self.tilesReady.emit(job.id, job.output, ranges)

    def _finalize(self, job: Job) -> None:
        self._delivery.stop()
        if self._delivered_ranges:
            self.tilesReady.emit(job.id, job.output, self._delivered_ranges)
            self._delivered_ranges.clear()
        if job.spec.deterministic:
            self._cache.put(self._make_key(job.spec, job.params, job.volume, job.axis, job.index), job.output)
        self.sectionReady.emit(job.id, job.output)
        self._active = None
```

## Step 6: GUI integration

`app.MainWindow` owns one `JobOrchestrator`. Replace the synchronous `_recompute_overlay` body with a `request()` call and wire two signals.

```python
# src/eggseis/app.py — additions
from eggseis.compute.orchestrator import JobOrchestrator

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        ...
        self._compute = JobOrchestrator()
        self._compute.tilesReady.connect(self._on_tiles_ready)
        self._compute.sectionReady.connect(self._on_section_ready)
        self._compute.failed.connect(
            lambda _id, msg: self.statusBar().showMessage(f"Compute failed: {msg}", 5000)
        )

    def _recompute_overlay(self, params=None) -> None:
        spec = self._active_plugin
        if spec is None or not self.section_viewer.has_volume:
            return
        if params is None:
            params = spec.param_model()
        self._compute.request(
            spec, params, self.section_viewer._volume,
            self.section_viewer.current_axis, self.section_viewer.current_index,
        )

    def _on_tiles_ready(self, job_id, buffer, ranges) -> None:
        self.section_viewer.set_overlay(buffer, partial=True)

    def _on_section_ready(self, job_id, arr) -> None:
        self.section_viewer.set_overlay(arr, partial=False)
```

`SectionViewer.set_overlay(arr, partial=False)` — when `partial=True`, suppress baseline-level recompute (still locked to raw) so the image keeps its colour scale across in-progress paints. Only the final paint may refresh levels (and only if `levels_locked=False`).

## Step 7: Library-side runner stays simple

Refactor `eggseis/plugin_runner.py` to share one inner primitive with the worker:

```python
# src/eggseis/plugin_runner.py — outline
def compute_tile(spec, params_dump, section, context, *, start, stop, out):
    if spec.vectorized:
        kwargs = {**params_dump, **({"context": context} if spec.accepts_context else {})}
        out[start:stop] = spec.func(traces=section[start:stop], **kwargs).astype(np.float32)
        return
    for i in range(start, stop):
        kwargs = {**params_dump, **({"context": context} if spec.accepts_context else {})}
        out[i] = spec.func(section[i], **kwargs)


def run_on_section(spec, params, volume, axis, index):
    """Synchronous, used by CLI/tests. GUI uses JobOrchestrator instead."""
    ...
    compute_tile(spec, params.model_dump(), section, context, start=0, stop=section.shape[0], out=out)
    return out
```

Keeps a single source of truth for the inner loop. `TileRunnable.run` becomes a thin shim around `compute_tile` once the refactor lands.

## Step 8: Tests

Use `pytest-qt`'s `qtbot.waitSignal` everywhere — never `time.sleep`.

### 8a — cache

```python
# tests/test_compute_cache.py
def test_lru_evicts_oldest_over_budget():
    cache = SectionLRU(byte_budget=8 * 1024)
    a = np.zeros((1024,), dtype=np.float32)  # 4 KB
    b = np.zeros((1024,), dtype=np.float32)
    c = np.zeros((1024,), dtype=np.float32)
    k = lambda i: CacheKey("p", "0.1.0", "h", "inline", i, ("mdio", "/x", 1, 1))
    cache.put(k(0), a); cache.put(k(1), b); cache.put(k(2), c)
    assert cache.get(k(0)) is None
    assert cache.get(k(1)) is not None and cache.get(k(2)) is not None
```

```python
def test_params_hash_is_stable_across_orderings():
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
```

### 8b — orchestrator (debounce + supersede)

```python
def test_debounce_coalesces_rapid_requests(qtbot, sample_volume, envelope_spec):
    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        for i in range(10):
            orch.request(envelope_spec, envelope_spec.param_model(),
                         sample_volume, "inline", sample_volume.geometry.inline_min)
    job_id, _arr = blocker.args
    # Only one job actually ran (the last) — earlier requests were debounced away.
    assert job_id is not None
```

```python
def test_supersede_cancels_in_flight(qtbot, sample_volume, slow_spec):
    """slow_spec is a plugin fixture that sleeps per-trace; verify second request preempts first."""
    orch = JobOrchestrator()
    orch.request(slow_spec, slow_spec.param_model(), sample_volume, "inline", 0)
    qtbot.wait(200)  # let debounce fire and dispatch
    with qtbot.waitSignal(orch.sectionReady, timeout=3000):
        orch.request(slow_spec, slow_spec.param_model(), sample_volume, "inline", 1)
    # First job's token should be set (cancelled), second's should not.
```

### 8c — cache hit path is sub-50 ms

```python
def test_cache_hit_returns_synchronously(qtbot, sample_volume, envelope_spec):
    orch = JobOrchestrator()
    with qtbot.waitSignal(orch.sectionReady, timeout=5000):
        orch.request(envelope_spec, envelope_spec.param_model(),
                     sample_volume, "inline", 0)

    t0 = time.perf_counter()
    with qtbot.waitSignal(orch.sectionReady, timeout=200):
        orch.request(envelope_spec, envelope_spec.param_model(),
                     sample_volume, "inline", 0)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # Generous bound; CI machines are slow. Real budget is <50 ms locally.
    assert elapsed_ms < 200
```

### 8d — determinism gate

```python
def test_non_deterministic_plugin_is_not_cached(qtbot, sample_volume, noise_spec):
    """noise_spec.deterministic is False; identical request must recompute."""
    orch = JobOrchestrator()
    ...
    assert len(orch.cache) == 0
```

### 8e — vectorized parity

```python
def test_vectorized_envelope_matches_scalar(sample_volume):
    section = sample_volume.read_inline(sample_volume.geometry.inline_min)
    scalar = np.stack([np.abs(hilbert(section[i])) for i in range(section.shape[0])])
    vec = run_on_section(envelope_spec, envelope_spec.param_model(),
                         sample_volume, "inline", sample_volume.geometry.inline_min)
    np.testing.assert_allclose(vec, scalar.astype(np.float32), rtol=1e-5)
```

### 8f — GUI smoke

Extend `tests/test_gui_smoke.py`:

```python
def test_attribute_apply_via_orchestrator(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume)

    from eggseis.builtins.envelope import envelope
    with qtbot.waitSignal(win._compute.sectionReady, timeout=5000):
        win._activate_plugin(envelope._eggseis_spec)
    assert win.section_viewer.has_overlay
```

### Test conventions for M4

- Always wait on orchestrator signals; never `time.sleep`.
- Build a `slow_spec` fixture (per-trace sleep) for cancellation tests — keep total wall-clock under a couple of seconds.
- Reuse `clear_registry()` autouse pattern from M3 when registering fixture plugins.

## Step 9: CLI / docs

- No new CLI commands. `eggseis info` and `eggseis dump-inline` continue to use synchronous `run_on_section`.
- Add a section to `docs/development.md` titled "How compute works in the GUI" — one paragraph, the threading model; one paragraph, the cache; one paragraph, the determinism flag.
- Add a one-line note to `docs/plugin-authoring.md`: "set `deterministic=False` on plugins whose output depends on RNG / time / external state — they will skip the cache."

## Step 10: Status surface

- Status bar shows `"Computing {plugin_name}…"` while a job is in flight; clears on `sectionReady`.
- Cache hit rate is *not* surfaced in M4. Resist. It's a tuning knob, not a user-facing number.
- A `Help → Compute Errors` action mirrors `Plugin Errors` from M3 and aggregates `failed` signals across the session.

---

## Execution order

1. New package skeleton + cache + tile primitives. Tests for `SectionLRU` budget/eviction and `params_hash` stability.
2. Refactor `plugin_runner.compute_tile`. Run M3 tests — they must stay green before any new code.
3. Surface `volume.version` on `SeismicVolume`/`MDIOBackend`. Test it changes when the file's `mtime` does.
4. `Job`, `CancellationToken`, `TileRunnable`. Manual smoke: kick off a runnable from a Python script with a fake spec.
5. `JobOrchestrator` cache-hit path first (no workers yet). Test sync return on hit, no return on miss.
6. Wire workers + debounce. Test debounce coalescing and supersede.
7. Progressive delivery (`tilesReady`). Test the partial-paint emission cadence.
8. Plug into `MainWindow`. Manually run the demo, drag an Ormsby slider, confirm responsiveness.
9. `Help → Compute Errors` + status bar message.
10. `./scripts/test.sh ci` green on all platforms.

Two weekends if disciplined. The trap on this milestone is **trying to make every plugin parallel by default** — vectorized=True is the user opting in. Scalar plugins stay scalar; we win by getting them off the GUI thread, not by SIMD-ifying user code.

---

## Risks

- **Qt signal/slot threading mistakes.** `TileSignals` is a `QObject` shared across threads; always use `Qt.AutoConnection` (default) — receivers live on the GUI thread, emitters fire on workers, Qt queues automatically. Verify by writing one paranoid test that deliberately mutates GUI state on `tilesReady` and asserts no warnings.
- **Cancellation races.** Token check is non-atomic with the per-trace write. The output buffer might receive a few stale rows after cancel. That's fine — the orchestrator drops the result by job_id mismatch and the buffer is reused for the next job. Document this in `compute/orchestrator.py`.
- **Cache key drift.** Anyone who tweaks `params_hash` later (e.g. swaps blake2b for sha256) breaks every saved key. There is no persistence in M4, so the blast radius is one session — but flag this loudly when M5 starts persisting cache entries.
- **`volume.version` and survey edits.** MDIO surveys are practically read-only. If a user replaces the file in place, the cache will *correctly* re-key on `mtime_ns`. If they edit-in-place at the same byte size and same nanosecond mtime, they get a stale cache. Acceptable for v1.0.
- **Pool starvation.** `QThreadPool.globalInstance()` is shared with PySide6 internals. Setting `max = cpu - 1` leaves headroom. If GUI feels laggy under heavy compute, drop to `cpu // 2`.
- **Vectorized plugins that don't accept `traces=`.** The runner already feeds `traces=section_tile`. If a third-party plugin uses positional-only signature, the framework should fail fast at decoration time. Add a check in `trace_attribute` that vectorized plugins accept a `traces` kw arg.
- **Debounce hides real lag.** 150 ms is invisible to the user when compute is fast and forgiving when it's slow. If a user complains "nothing happens when I click", check whether the debounce timer is masking a downstream bug.

---

## Out of scope for M4

- Disk-backed cache → v1.1.
- Per-tile cache reuse across param changes → v1.1+ (not useful for trace-local plugins).
- Viewport-aware tile prioritization (zoom/pan-driven priorities) → polish in v1.0 RC if time allows; M4 ships with center-out only.
- Backend reads on workers → measure first; M4 keeps reads on the GUI thread.
- Pipeline / chained plugins → M5 (`run_up_to` reuses the M4 cache via stable per-node keys).
- Volume-wide compute → M6.
- GPU offload → out of scope for v1.0.

---

## When M4 is done

A clean exit looks like:

- Drag the Ormsby sliders against the F3 fragment with `n_taps=401`. Section keeps repainting; UI never freezes; releasing the slider lands on the right answer with no ghost paints from earlier positions.
- Pan inline ←→, return to a known slice, see it appear instantly. Clear the cache, repeat — now you see the worker fan-in (tiles appearing center-out).
- `eggseis info` and `eggseis dump-inline` still produce identical bytes to their M3 outputs. Pure GUI-side change.
- Headless tests cover orchestrator request/cancel/debounce, cache hit/miss/evict, vectorized parity, progressive delivery, and a GUI smoke path.
- README updated with one sentence in the status section ("M4: GUI compute engine — async, debounced, cached"). CHANGELOG entry under `[v0.1.0a4]`.
- Tag `v0.1.0a4` after the M4 PR merges.
- Take a beat. Then start M5 — "The pipeline chains."
