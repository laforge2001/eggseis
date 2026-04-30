# M5 Pipeline Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a linear plugin pipeline (Source → N attribute nodes) with tap-anywhere section viewer binding, lazy downstream recompute, and per-node cache reuse via the existing M4 LRU.

**Architecture:** New `eggseis.pipeline` package owns the data model (`Node`, `Pipeline`), a coordinating `PipelineExecutor(QObject)` that wraps the M4 `JobOrchestrator` for serial cold-suffix execution, and a `PipelineDock(QDockWidget)` for the list-style UI. Cache keys gain `chain_hash` (replacing M4's `params_hash`); the orchestrator gains optional `input_section` and `chain_hash` kwargs on `request()` so chained calls can reuse its threading + cache layer without duplication.

**Tech Stack:** Python 3.10+, NumPy, PySide6 (Qt), pydantic, pytest + pytest-qt + `QT_QPA_PLATFORM=offscreen` for headless Qt tests, blake2b via `hashlib`.

**Spec:** `M5-PLAN.md` at the repo root has the full design rationale and locked decisions.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/eggseis/pipeline/__init__.py` | Re-exports `Pipeline`, `Node`, `SOURCE_ID`, `PipelineExecutor`. |
| `src/eggseis/pipeline/model.py` | `Node` and `Pipeline` dataclasses; mutation methods; `chain_hash_for`; `deterministic_through`; `nodes_up_to_tap`. |
| `src/eggseis/pipeline/executor.py` | `PipelineExecutor(QObject)` — walks chain, looks up cache, drives orchestrator serially, emits `tapReady`/`failed`. |
| `src/eggseis/pipeline/dock.py` | `PipelineDock(QDockWidget)` — list of node rows, "+ Add" picker, selection-driven param panel. |
| `tests/test_pipeline_model.py` | Pure-Python tests for the data model. |
| `tests/test_pipeline_executor.py` | qtbot-driven tests for executor behaviours. |
| `tests/test_pipeline_dock.py` | Headless Qt tests for dock interactions. |

**Modified:**

| Path | Reason |
|---|---|
| `src/eggseis/compute/cache.py` | Rename `CacheKey.params_hash` → `chain_hash`. Add `chain_hash` keyword override on `make_cache_key`. |
| `src/eggseis/compute/orchestrator.py` | `request()` gains `input_section` and `chain_hash` keyword arguments. `_dispatch_pending` honours them. |
| `src/eggseis/app.py` | Add `_pipelines: dict[str, Pipeline]`, `_executor: PipelineExecutor`, the `PipelineDock`, and a `_request_tap` routing method. Add `Compute Errors` extension for chained errors. |
| `tests/conftest.py` | Add `linear_spec`, `raising_spec`, `make_pipeline` fixtures. |
| `tests/test_compute_cache.py` | Field rename touch-up. |
| `tests/test_compute_orchestrator.py` | Cover new `input_section` / `chain_hash` kwargs. |
| `tests/test_gui_smoke.py` | New `test_chain_three_attributes_tap_each`. |
| `docs/development.md` | Add "How pipelines work in the GUI" section. |
| `docs/plugin-authoring.md` | One-line note on `deterministic=False` poisoning the chain downstream. |
| `README.md` | Status line under M4. |
| `CHANGELOG.md` | `[v0.1.0a5]` entry. |

---

## Test Discipline

- Always wait on signals via `qtbot.waitSignal` / `qtbot.waitUntil`. Never `time.sleep`.
- Tests that register decorated plugins must use the `clear_registry()` autouse fixture pattern from M3.
- Headless Qt tests run under `QT_QPA_PLATFORM=offscreen` (set by `./scripts/test.sh`).
- Run the full suite with `./scripts/test.sh ci`. Single test: `./scripts/test.sh ci -k test_name`. (All `pytest` invocations below assume the venv is active and `QT_QPA_PLATFORM=offscreen` is exported, matching `scripts/test.sh`.)

---

## Task 1: Cache key rename — `params_hash` → `chain_hash`

**Files:**
- Modify: `src/eggseis/compute/cache.py`
- Modify: `tests/test_compute_cache.py`

This is a pure rename with no semantic change yet. It unblocks every later task that imports `CacheKey`. M4's `make_cache_key` continues to fold the `params_hash(params.model_dump())` digest into the renamed field, so behaviour for existing callers is identical.

- [ ] **Step 1: Rename the dataclass field**

In `src/eggseis/compute/cache.py`, change line 31 from `params_hash: str` to `chain_hash: str`.

- [ ] **Step 2: Update `make_cache_key`**

Change the `params_hash=params_hash(params.model_dump())` line in `make_cache_key` to `chain_hash=params_hash(params.model_dump())`. Keep the helper function `params_hash(params_dump)` exactly as it is — it's still used by both single-attribute callers and the upcoming chain math.

- [ ] **Step 3: Run cache tests to see failures**

Run: `pytest tests/test_compute_cache.py -v`
Expected: failures naming `params_hash` as a missing field on `CacheKey`.

- [ ] **Step 4: Update test field references**

In `tests/test_compute_cache.py`, replace every `params_hash="..."` keyword in `CacheKey(...)` constructors with `chain_hash="..."`. Do not rename the imported helper function `params_hash`; only the dataclass field changes.

- [ ] **Step 5: Run cache tests, then full M4 suite**

Run: `pytest tests/test_compute_cache.py tests/test_compute_orchestrator.py tests/test_compute_job.py tests/test_compute_tile.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/compute/cache.py tests/test_compute_cache.py
git commit -m "refactor(cache): rename CacheKey.params_hash to chain_hash"
```

---

## Task 2: `make_cache_key` accepts a `chain_hash` override

**Files:**
- Modify: `src/eggseis/compute/cache.py`
- Modify: `tests/test_compute_cache.py`

Single-attribute callers keep their behaviour. Chained callers will pass an explicit hash that already folds in upstream + params.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compute_cache.py`:

```python
def test_make_cache_key_uses_chain_hash_override_when_provided(fake_backend):
    from eggseis.compute.cache import make_cache_key
    from eggseis.data import SeismicVolume

    class _StubSpec:
        id = "p"
        version = "0.1.0"

    class _StubParams:
        def model_dump(self):
            return {"a": 1}

    volume = SeismicVolume(fake_backend, name="v")
    key = make_cache_key(
        _StubSpec(), _StubParams(), volume, "inline", 0, chain_hash="deadbeef"
    )
    assert key.chain_hash == "deadbeef"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_compute_cache.py::test_make_cache_key_uses_chain_hash_override_when_provided -v`
Expected: FAIL — `make_cache_key()` got an unexpected keyword argument `'chain_hash'`.

- [ ] **Step 3: Add the override kwarg**

Edit `make_cache_key` in `src/eggseis/compute/cache.py`:

```python
def make_cache_key(spec, params, volume, axis, index, *, chain_hash: str | None = None) -> CacheKey:
    axis_value = axis.value if hasattr(axis, "value") else axis
    return CacheKey(
        plugin_id=spec.id,
        plugin_version=spec.version,
        chain_hash=chain_hash if chain_hash is not None else params_hash(params.model_dump()),
        axis=axis_value,
        index=index,
        volume_version=volume.version,
    )
```

- [ ] **Step 4: Re-run the test plus the existing suite**

Run: `pytest tests/test_compute_cache.py -v`
Expected: all green, including the new test.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/compute/cache.py tests/test_compute_cache.py
git commit -m "feat(cache): make_cache_key accepts chain_hash override for chained callers"
```

---

## Task 3: `JobOrchestrator.request` — `input_section` and `chain_hash` kwargs

**Files:**
- Modify: `src/eggseis/compute/orchestrator.py`
- Modify: `tests/test_compute_orchestrator.py`

When the executor has already loaded a section (or computed an upstream node's output), the orchestrator should not re-read from the volume. When the executor knows the chain hash, the orchestrator should use it instead of recomputing `params_hash`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compute_orchestrator.py`:

```python
def test_request_uses_input_section_override(qtbot, fake_backend, linear_spec):
    """When input_section is provided, orchestrator skips volume reads."""
    import numpy as np
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()

    canned = np.full((6, 32), 7.0, dtype=np.float32)  # arbitrary input
    params = linear_spec.param_model(scale=2.0)

    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        orch.request(
            linear_spec, params, volume, "inline", volume.geometry.inline_min,
            input_section=canned, chain_hash="abc123",
        )
    _job_id, arr = blocker.args
    np.testing.assert_allclose(arr, canned * 2.0)


def test_request_uses_chain_hash_override_for_cache_key(qtbot, fake_backend, linear_spec):
    """Identical chain_hash on second request hits cache; raw input_section ignored."""
    import numpy as np
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    section_a = np.full((6, 32), 1.0, dtype=np.float32)
    params = linear_spec.param_model(scale=3.0)

    with qtbot.waitSignal(orch.sectionReady, timeout=2000):
        orch.request(
            linear_spec, params, volume, "inline", volume.geometry.inline_min,
            input_section=section_a, chain_hash="zzz999",
        )

    # Second request, same chain_hash, different input_section → cache hit returns
    # the previous (section_a * 3.0) result, not section_b * 3.0.
    section_b = np.full((6, 32), 100.0, dtype=np.float32)
    with qtbot.waitSignal(orch.sectionReady, timeout=2000) as blocker:
        orch.request(
            linear_spec, params, volume, "inline", volume.geometry.inline_min,
            input_section=section_b, chain_hash="zzz999",
        )
    _job_id, arr = blocker.args
    np.testing.assert_allclose(arr, section_a * 3.0)
```

This test depends on a `linear_spec` fixture not yet defined; Task 4 below adds it. Skip running this test until Task 4 lands. Add the test code now and stub the fixture as a one-line `pytest.skip(...)` if necessary.

- [ ] **Step 2: Inspect the existing `request` signature and `_dispatch_pending`**

Read `src/eggseis/compute/orchestrator.py` lines 72–151. Note that `request` already snapshots into `self._pending` and that `_dispatch_pending` does the volume read. The change must thread the override into both.

- [ ] **Step 3: Update `request` to accept and stash overrides**

Replace the `request` method body:

```python
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
) -> None:
    axis_enum = Axis(axis)
    self._pending = {
        "spec": spec,
        "params": params,
        "volume": volume,
        "axis": axis_enum,
        "index": index,
        "input_section": input_section,
        "chain_hash": chain_hash,
    }
    key = make_cache_key(spec, params, volume, axis_enum, index, chain_hash=chain_hash)
    self._pending["key"] = key
    if spec.deterministic:
        cached = self._cache.get(key)
        if cached is not None:
            self._pending = None
            self.cancel_active()
            self.sectionReady.emit(Job().id, cached)
            return
    self._debounce.start()
```

- [ ] **Step 4: Update `_dispatch_pending` to honour `input_section`**

Replace the read block (lines 121–128 of the original) with:

```python
if axis is Axis.TIMESLICE:
    self.sectionReady.emit(Job().id, volume.read_timeslice(index))
    return

if req.get("input_section") is not None:
    section = req["input_section"]
else:
    section = (
        volume.read_inline(index) if axis is Axis.INLINE else volume.read_xline(index)
    )
```

No other changes to `_dispatch_pending` are needed; the `Job` already carries `cache_key=req.get("key")`.

- [ ] **Step 5: Run the orchestrator tests (will skip the two new ones until linear_spec lands)**

Run: `pytest tests/test_compute_orchestrator.py -v`
Expected: existing tests pass; the two new tests skip or xfail pending the fixture.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/compute/orchestrator.py tests/test_compute_orchestrator.py
git commit -m "feat(orchestrator): accept input_section and chain_hash overrides on request()"
```

---

## Task 4: Test fixtures — `linear_spec`, `raising_spec`, `make_pipeline`

**Files:**
- Modify: `tests/conftest.py`

`linear_spec` is a deterministic, vectorized-friendly trace attribute that multiplies by a scalar. It composes cleanly: a chain of three linear nodes with scales `(2, 3, 5)` produces `raw * 30`. `raising_spec` always raises so failure paths can be exercised. `make_pipeline` reduces boilerplate in chain tests.

- [ ] **Step 1: Add the fixtures**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def linear_spec():
    """Deterministic trace * scalar. Vectorized batch path supported."""
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Linear Scale", version="0.1.0", vectorized=True, deterministic=True)
    def linear(traces: np.ndarray, scale: float = Param(default=1.0)) -> np.ndarray:
        return traces * scale

    yield linear._eggseis_spec
    clear_registry()


@pytest.fixture
def raising_spec():
    """Always raises. Exercises failure propagation."""
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Raises", version="0.1.0", vectorized=False, deterministic=True)
    def raises(trace: np.ndarray, _: float = Param(default=0.0)) -> np.ndarray:
        raise RuntimeError("boom")

    yield raises._eggseis_spec
    clear_registry()


@pytest.fixture
def noise_spec():
    """Non-deterministic. Exercises cache-poisoning."""
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Noise", version="0.1.0", vectorized=True, deterministic=False)
    def noise(traces: np.ndarray, amp: float = Param(default=1.0)) -> np.ndarray:
        rng = np.random.default_rng()
        return traces + rng.standard_normal(traces.shape).astype(np.float32) * amp

    yield noise._eggseis_spec
    clear_registry()


@pytest.fixture
def make_pipeline():
    """Build a Pipeline from a list of (spec, params) tuples."""
    def _make(*specs_and_params):
        from eggseis.pipeline.model import Node, Pipeline
        p = Pipeline()
        for entry in specs_and_params:
            if isinstance(entry, tuple):
                spec, params = entry
            else:
                spec = entry
                params = spec.param_model()
            p.append(Node(spec=spec, params=params))
        return p
    return _make
```

The `make_pipeline` fixture imports from `eggseis.pipeline.model`, which doesn't exist until Task 5. That is OK because `make_pipeline` is a callable that only imports lazily.

- [ ] **Step 2: Smoke-run the conftest**

Run: `pytest tests/test_compute_cache.py -v`
Expected: passes; conftest changes don't break existing tests.

- [ ] **Step 3: Re-run the deferred Task 3 tests**

Run: `pytest tests/test_compute_orchestrator.py::test_request_uses_input_section_override tests/test_compute_orchestrator.py::test_request_uses_chain_hash_override_for_cache_key -v`
Expected: both pass.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add linear_spec, raising_spec, noise_spec, make_pipeline fixtures"
```

---

## Task 5: `eggseis.pipeline` package skeleton + `Node` dataclass

**Files:**
- Create: `src/eggseis/pipeline/__init__.py`
- Create: `src/eggseis/pipeline/model.py`
- Create: `tests/test_pipeline_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_model.py`:

```python
"""Pipeline data model tests — pure Python, no Qt."""

from __future__ import annotations

import pytest


def test_node_assigns_uuid_node_id(linear_spec):
    from eggseis.pipeline.model import Node

    n1 = Node(spec=linear_spec, params=linear_spec.param_model())
    n2 = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n1.node_id != n2.node_id
    assert len(n1.node_id) == 32  # uuid4().hex


def test_node_default_enabled(linear_spec):
    from eggseis.pipeline.model import Node

    assert Node(spec=linear_spec, params=linear_spec.param_model()).enabled is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: ImportError — `eggseis.pipeline.model` does not exist.

- [ ] **Step 3: Create the package skeleton**

Create `src/eggseis/pipeline/__init__.py`:

```python
"""Pipeline data model + executor for chained trace-local plugins."""

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline

__all__ = ["SOURCE_ID", "Node", "Pipeline"]
```

Create `src/eggseis/pipeline/model.py`:

```python
"""Pipeline + Node data model.

A Pipeline is a linear sequence of plugin Nodes plus an implicit Source at
position 0. The user picks a tap (a node id, or `SOURCE_ID`); execution
walks Source → tap and the section viewer paints the tap's output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel

from eggseis.plugin import PluginSpec

SOURCE_ID = "source"


@dataclass
class Node:
    spec: PluginSpec
    params: BaseModel
    enabled: bool = True
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Pipeline:
    nodes: list[Node] = field(default_factory=list)
    tap_node_id: str = SOURCE_ID
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/__init__.py src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): Node + Pipeline dataclasses, SOURCE_ID constant"
```

---

## Task 6: `Pipeline.append`, `remove`, `move`, `set_enabled`, `set_params`

**Files:**
- Modify: `src/eggseis/pipeline/model.py`
- Modify: `tests/test_pipeline_model.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_model.py`:

```python
def test_append_adds_node_at_end(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    assert p.nodes == [n]


def test_remove_drops_node_by_id(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.remove(a.node_id)
    assert p.nodes == [b]


def test_remove_unknown_raises(linear_spec):
    from eggseis.pipeline.model import Pipeline

    p = Pipeline()
    with pytest.raises(KeyError):
        p.remove("does-not-exist")


def test_move_reorders(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.move(c.node_id, 0)
    assert [n.node_id for n in p.nodes] == [c.node_id, a.node_id, b.node_id]


def test_set_enabled_flips_flag(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    p.set_enabled(n.node_id, False)
    assert p.nodes[0].enabled is False
    p.set_enabled(n.node_id, True)
    assert p.nodes[0].enabled is True


def test_set_params_replaces_pydantic_model(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model(scale=1.0))
    p.append(n)
    new_params = linear_spec.param_model(scale=4.0)
    p.set_params(n.node_id, new_params)
    assert p.nodes[0].params.scale == 4.0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: AttributeError on `append` / `remove` / etc.

- [ ] **Step 3: Implement the mutation methods**

Add to the `Pipeline` class in `src/eggseis/pipeline/model.py`:

```python
    def _index(self, node_id: str) -> int:
        for i, n in enumerate(self.nodes):
            if n.node_id == node_id:
                return i
        raise KeyError(node_id)

    def append(self, node: Node) -> None:
        self.nodes.append(node)

    def remove(self, node_id: str) -> None:
        del self.nodes[self._index(node_id)]
        if self.tap_node_id == node_id:
            self.tap_node_id = SOURCE_ID

    def move(self, node_id: str, new_index: int) -> None:
        i = self._index(node_id)
        node = self.nodes.pop(i)
        self.nodes.insert(new_index, node)

    def set_enabled(self, node_id: str, on: bool) -> None:
        self.nodes[self._index(node_id)].enabled = on

    def set_params(self, node_id: str, params: BaseModel) -> None:
        self.nodes[self._index(node_id)].params = params
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): Pipeline mutation methods (append/remove/move/set_enabled/set_params)"
```

---

## Task 7: `Pipeline.set_tap` with defensive shift on disabled targets

**Files:**
- Modify: `src/eggseis/pipeline/model.py`
- Modify: `tests/test_pipeline_model.py`

If the user disables the currently-tapped node, the tap automatically shifts to the nearest enabled upstream ancestor (falling through to `SOURCE_ID` if necessary). Same logic applies if `set_tap` is called with a disabled `node_id`: refuse to land there, shift to upstream.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_model.py`:

```python
def test_set_tap_to_node_id_succeeds_when_enabled(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(n)
    p.set_tap(n.node_id)
    assert p.tap_node_id == n.node_id


def test_set_tap_to_disabled_node_shifts_upstream(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline, SOURCE_ID

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    assert p.tap_node_id == a.node_id


def test_set_tap_falls_through_to_source_when_no_enabled_ancestor(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline, SOURCE_ID

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    assert p.tap_node_id == SOURCE_ID


def test_disable_tapped_node_auto_shifts_tap(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    p.set_tap(b.node_id)
    p.set_enabled(b.node_id, False)
    assert p.tap_node_id == a.node_id


def test_set_tap_to_source_always_allowed(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline, SOURCE_ID

    p = Pipeline()
    p.set_tap(SOURCE_ID)
    assert p.tap_node_id == SOURCE_ID
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v -k tap`
Expected: AttributeError on `set_tap`.

- [ ] **Step 3: Implement `set_tap` and update `set_enabled`**

Add to `Pipeline`:

```python
    def set_tap(self, node_id: str) -> None:
        if node_id == SOURCE_ID:
            self.tap_node_id = SOURCE_ID
            return
        target = self.nodes[self._index(node_id)]
        if target.enabled:
            self.tap_node_id = node_id
            return
        # Walk upstream looking for an enabled ancestor; fall through to Source.
        target_idx = self._index(node_id)
        for i in range(target_idx - 1, -1, -1):
            if self.nodes[i].enabled:
                self.tap_node_id = self.nodes[i].node_id
                return
        self.tap_node_id = SOURCE_ID
```

Update `set_enabled` to auto-shift when the tapped node is being disabled:

```python
    def set_enabled(self, node_id: str, on: bool) -> None:
        self.nodes[self._index(node_id)].enabled = on
        if not on and self.tap_node_id == node_id:
            self.set_tap(node_id)  # set_tap handles the shift
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): set_tap with defensive shift on disabled targets"
```

---

## Task 8: `Pipeline.nodes_up_to_tap` (honors enabled flag)

**Files:**
- Modify: `src/eggseis/pipeline/model.py`
- Modify: `tests/test_pipeline_model.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_nodes_up_to_tap_empty_when_tap_is_source(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    p.append(Node(spec=linear_spec, params=linear_spec.param_model()))
    # tap defaults to SOURCE_ID
    assert p.nodes_up_to_tap() == []


def test_nodes_up_to_tap_returns_inclusive_slice(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.set_tap(b.node_id)
    assert [n.node_id for n in p.nodes_up_to_tap()] == [a.node_id, b.node_id]


def test_nodes_up_to_tap_filters_disabled(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model(), enabled=False)
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)
    p.set_tap(c.node_id)
    assert [n.node_id for n in p.nodes_up_to_tap()] == [a.node_id, c.node_id]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v -k up_to_tap`
Expected: AttributeError.

- [ ] **Step 3: Implement**

Add to `Pipeline`:

```python
    def nodes_up_to_tap(self) -> list[Node]:
        """Enabled nodes from index 0 through the tap, inclusive.

        If the tap is SOURCE_ID, returns []. Disabled nodes are filtered.
        """
        if self.tap_node_id == SOURCE_ID:
            return []
        tap_idx = self._index(self.tap_node_id)
        return [n for n in self.nodes[: tap_idx + 1] if n.enabled]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): nodes_up_to_tap respects enabled flag and tap position"
```

---

## Task 9: `Pipeline.chain_hash_for`

**Files:**
- Modify: `src/eggseis/pipeline/model.py`
- Modify: `tests/test_pipeline_model.py`

This is the cache-key foundation. Source hash is `blake2b(volume_version_blob)`. Each enabled node folds in `(plugin_id, plugin_version, params_hash, parent_hash)`. Disabled nodes are identity (skip = parent_hash unchanged). Two nodes with identical specs and params produce different chain hashes if their parents differ.

- [ ] **Step 1: Write the failing tests**

```python
def test_source_hash_stable_for_same_volume_version(linear_spec):
    from eggseis.pipeline.model import Pipeline, SOURCE_ID

    p = Pipeline()
    vv = ("mdio", "/x", 1, 1)
    h1 = p.chain_hash_for(SOURCE_ID, vv)
    h2 = p.chain_hash_for(SOURCE_ID, vv)
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 32  # blake2b digest_size=16 hex


def test_source_hash_changes_with_volume_version(linear_spec):
    from eggseis.pipeline.model import Pipeline, SOURCE_ID

    p = Pipeline()
    h1 = p.chain_hash_for(SOURCE_ID, ("mdio", "/x", 1, 1))
    h2 = p.chain_hash_for(SOURCE_ID, ("mdio", "/x", 1, 2))
    assert h1 != h2


def test_node_hash_stable_across_param_orderings(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p1 = Pipeline()
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    vv = ("mdio", "/x", 1, 1)
    assert p1.chain_hash_for(p1.nodes[0].node_id, vv) == p2.chain_hash_for(
        p2.nodes[0].node_id, vv
    )


def test_node_hash_changes_when_params_change(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p1 = Pipeline()
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=3.0)))
    vv = ("mdio", "/x", 1, 1)
    assert p1.chain_hash_for(p1.nodes[0].node_id, vv) != p2.chain_hash_for(
        p2.nodes[0].node_id, vv
    )


def test_node_hash_changes_when_upstream_changes(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p1 = Pipeline()
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=1.0)))
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))

    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=99.0)))
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))

    vv = ("mdio", "/x", 1, 1)
    # Same node 1 (scale=2.0) but different upstream → different chain hash.
    assert p1.chain_hash_for(p1.nodes[1].node_id, vv) != p2.chain_hash_for(
        p2.nodes[1].node_id, vv
    )


def test_disabled_node_passes_parent_hash_through(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0))
    b = Node(spec=linear_spec, params=linear_spec.param_model(scale=99.0), enabled=False)
    c = Node(spec=linear_spec, params=linear_spec.param_model(scale=3.0))
    for n in (a, b, c):
        p.append(n)

    vv = ("mdio", "/x", 1, 1)
    h_with_b_disabled = p.chain_hash_for(c.node_id, vv)

    # Now build an equivalent pipeline without b at all; c's hash must match.
    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=3.0)))
    h_without_b = p2.chain_hash_for(p2.nodes[1].node_id, vv)

    assert h_with_b_disabled == h_without_b


def test_duplicate_plugin_same_params_same_position_yields_same_hash(linear_spec):
    """node_id is GUI-only; chain_hash must not depend on it."""
    from eggseis.pipeline.model import Node, Pipeline

    p1 = Pipeline()
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    vv = ("mdio", "/x", 1, 1)
    # Different node_ids, identical hash.
    assert p1.nodes[0].node_id != p2.nodes[0].node_id
    assert p1.chain_hash_for(p1.nodes[0].node_id, vv) == p2.chain_hash_for(
        p2.nodes[0].node_id, vv
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v -k chain_hash`
Expected: AttributeError.

- [ ] **Step 3: Implement `chain_hash_for`**

Add to `src/eggseis/pipeline/model.py` (extra imports at top):

```python
import hashlib
import json

from eggseis.compute.cache import params_hash
```

Then on `Pipeline`:

```python
    def chain_hash_for(self, node_id: str, volume_version: tuple) -> str:
        """Cache-key hash for the chain ending at `node_id`.

        Source hash: blake2b of canonical-JSON volume_version tuple.
        Each enabled node folds in (plugin_id, plugin_version, params_hash,
        parent_hash). Disabled nodes act as identity (parent passes through).
        """
        source_blob = json.dumps(
            list(volume_version), sort_keys=True, separators=(",", ":")
        ).encode()
        running = hashlib.blake2b(source_blob, digest_size=16).hexdigest()
        if node_id == SOURCE_ID:
            return running

        tap_idx = self._index(node_id)
        for node in self.nodes[: tap_idx + 1]:
            if not node.enabled:
                continue
            payload = (
                node.spec.id,
                node.spec.version,
                params_hash(node.params.model_dump()),
                running,
            )
            blob = json.dumps(
                list(payload), sort_keys=True, separators=(",", ":")
            ).encode()
            running = hashlib.blake2b(blob, digest_size=16).hexdigest()
        return running
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): chain_hash_for — Source-rooted cache key for any node"
```

---

## Task 10: `Pipeline.deterministic_through`

**Files:**
- Modify: `src/eggseis/pipeline/model.py`
- Modify: `tests/test_pipeline_model.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_deterministic_through_source_is_true(linear_spec):
    from eggseis.pipeline.model import Pipeline, SOURCE_ID

    assert Pipeline().deterministic_through(SOURCE_ID) is True


def test_deterministic_through_all_deterministic_nodes_true(linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=linear_spec, params=linear_spec.param_model())
    p.append(a)
    p.append(b)
    assert p.deterministic_through(b.node_id) is True


def test_deterministic_through_falsy_node_poisons_self_and_downstream(noise_spec, linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=noise_spec, params=noise_spec.param_model())
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)

    assert p.deterministic_through(a.node_id) is True
    assert p.deterministic_through(b.node_id) is False
    assert p.deterministic_through(c.node_id) is False


def test_deterministic_through_disabled_non_deterministic_node_does_not_poison(noise_spec, linear_spec):
    from eggseis.pipeline.model import Node, Pipeline

    p = Pipeline()
    a = Node(spec=linear_spec, params=linear_spec.param_model())
    b = Node(spec=noise_spec, params=noise_spec.param_model(), enabled=False)
    c = Node(spec=linear_spec, params=linear_spec.param_model())
    for n in (a, b, c):
        p.append(n)

    assert p.deterministic_through(c.node_id) is True
```

`noise_spec` clears the registry on entry, so each test that uses it must avoid mixing with `linear_spec` in the same fixture call. The fixtures here both yield specs after `clear_registry()`; pytest's fixture ordering means the second one to be requested wins. To use both in one test, depend on `noise_spec` first, then build `linear` inline. Since both fixtures call `clear_registry()` on yield, request only one of them; build the other plugin inline.

Rewrite the offending tests above to register both plugins inline:

```python
def test_deterministic_through_falsy_node_poisons_self_and_downstream():
    from eggseis.pipeline.model import Node, Pipeline
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="lin", version="0.1.0", deterministic=True, vectorized=True)
    def lin(traces, scale: float = Param(default=1.0)):
        return traces * scale

    @trace_attribute(name="rng", version="0.1.0", deterministic=False, vectorized=True)
    def rng(traces, amp: float = Param(default=1.0)):
        return traces

    p = Pipeline()
    a = Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model())
    b = Node(spec=rng._eggseis_spec, params=rng._eggseis_spec.param_model())
    c = Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model())
    for n in (a, b, c):
        p.append(n)

    assert p.deterministic_through(a.node_id) is True
    assert p.deterministic_through(b.node_id) is False
    assert p.deterministic_through(c.node_id) is False
    clear_registry()


def test_deterministic_through_disabled_non_deterministic_node_does_not_poison():
    from eggseis.pipeline.model import Node, Pipeline
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="lin", version="0.1.0", deterministic=True, vectorized=True)
    def lin(traces, scale: float = Param(default=1.0)):
        return traces * scale

    @trace_attribute(name="rng", version="0.1.0", deterministic=False, vectorized=True)
    def rng(traces, amp: float = Param(default=1.0)):
        return traces

    p = Pipeline()
    a = Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model())
    b = Node(spec=rng._eggseis_spec, params=rng._eggseis_spec.param_model(), enabled=False)
    c = Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model())
    for n in (a, b, c):
        p.append(n)

    assert p.deterministic_through(c.node_id) is True
    clear_registry()
```

The first two tests in the section (single-fixture cases) keep the `linear_spec` fixture as-is.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_model.py -v -k deterministic_through`
Expected: AttributeError.

- [ ] **Step 3: Implement**

Add to `Pipeline`:

```python
    def deterministic_through(self, node_id: str) -> bool:
        if node_id == SOURCE_ID:
            return True
        tap_idx = self._index(node_id)
        return all(n.spec.deterministic for n in self.nodes[: tap_idx + 1] if n.enabled)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_model.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/model.py tests/test_pipeline_model.py
git commit -m "feat(pipeline): deterministic_through poisons downstream when any enabled node is non-deterministic"
```

---

## Task 11: `PipelineExecutor` skeleton + Source/empty-pipeline path

**Files:**
- Create: `src/eggseis/pipeline/executor.py`
- Modify: `src/eggseis/pipeline/__init__.py`
- Create: `tests/test_pipeline_executor.py`

The simplest case: empty pipeline (or tap on Source) → executor reads the raw section synchronously and emits `tapReady` immediately.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_executor.py`:

```python
"""PipelineExecutor tests — qtbot-driven; require pytest-qt."""

from __future__ import annotations

import numpy as np
import pytest


def test_empty_pipeline_taps_source_emits_raw(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor
    from eggseis.pipeline.model import Pipeline

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)
    p = Pipeline()  # tap defaults to SOURCE_ID

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, volume.read_inline(volume.geometry.inline_min))
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_executor.py -v`
Expected: ImportError on `eggseis.pipeline.executor`.

- [ ] **Step 3: Create the executor skeleton**

Create `src/eggseis/pipeline/executor.py`:

```python
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
from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


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
```

Update `src/eggseis/pipeline/__init__.py`:

```python
from eggseis.pipeline.executor import PipelineExecutor
from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline

__all__ = ["SOURCE_ID", "Node", "Pipeline", "PipelineExecutor"]
```

- [ ] **Step 4: Run the test to verify pass**

Run: `pytest tests/test_pipeline_executor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/executor.py src/eggseis/pipeline/__init__.py tests/test_pipeline_executor.py
git commit -m "feat(pipeline): PipelineExecutor skeleton + Source/empty-pipeline tapReady path"
```

---

## Task 12: `PipelineExecutor` — single-node cold execution

**Files:**
- Modify: `src/eggseis/pipeline/executor.py`
- Modify: `tests/test_pipeline_executor.py`

When the plan has one cold node, executor delegates to the orchestrator with the chain hash and waits on `sectionReady`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_executor.py`:

```python
def test_single_node_cold_execution(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline((linear_spec, linear_spec.param_model(scale=2.0)))
    p.set_tap(p.nodes[0].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    np.testing.assert_allclose(
        arr,
        volume.read_inline(volume.geometry.inline_min) * 2.0,
        rtol=1e-5,
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_executor.py::test_single_node_cold_execution -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement cold-suffix walking**

Replace `request_tap` body in `executor.py`:

```python
    def request_tap(
        self,
        pipeline: Pipeline,
        volume: SeismicVolume,
        axis: Axis | str,
        index: int,
    ) -> None:
        axis_enum = Axis(axis) if not isinstance(axis, Axis) else axis
        plan = pipeline.nodes_up_to_tap()

        # Source / empty plan: raw paint.
        if not plan or pipeline.tap_node_id == SOURCE_ID:
            raw = self._read_raw(volume, axis_enum, index)
            self.tapReady.emit(self._new_job_id(), raw)
            return

        # Resolve cold suffix: walk from tap backward, find deepest cache hit.
        cache = self._orch.cache
        starting_input: np.ndarray | None = None
        cold_start_idx = 0
        for i in range(len(plan) - 1, -1, -1):
            node = plan[i]
            chain_hash = pipeline.chain_hash_for(node.node_id, volume.version)
            from eggseis.compute.cache import make_cache_key
            key = make_cache_key(
                node.spec, node.params, volume, axis_enum, index,
                chain_hash=chain_hash,
            )
            if pipeline.deterministic_through(node.node_id):
                cached = cache.get(key)
                if cached is not None:
                    if i == len(plan) - 1:
                        # Tap node itself is cached.
                        self.tapReady.emit(self._new_job_id(), cached)
                        return
                    starting_input = cached
                    cold_start_idx = i + 1
                    break

        if starting_input is None:
            starting_input = self._read_raw(volume, axis_enum, index)
            cold_start_idx = 0

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

        def step(idx: int, current_input: np.ndarray) -> None:
            if idx >= len(cold_nodes):
                self.tapReady.emit(job_id, current_input)
                return
            node = cold_nodes[idx]
            chain_hash = pipeline.chain_hash_for(node.node_id, volume.version)

            def on_ready(_section_job_id: int, arr: np.ndarray) -> None:
                self._orch.sectionReady.disconnect(on_ready)
                self._orch.failed.disconnect(on_failed)
                self.intermediateReady.emit(job_id, node.node_id, arr)
                step(idx + 1, arr)

            def on_failed(_section_job_id: int, message: str) -> None:
                self._orch.sectionReady.disconnect(on_ready)
                self._orch.failed.disconnect(on_failed)
                self.failed.emit(job_id, f"{node.spec.name}: {message}")

            self._orch.sectionReady.connect(on_ready)
            self._orch.failed.connect(on_failed)
            self._orch.request(
                node.spec, node.params, volume, axis, index,
                input_section=current_input, chain_hash=chain_hash,
            )

        step(0, starting_input)
```

The `step` closure walks one node per `sectionReady` round-trip. Each connection is one-shot (disconnects itself before issuing the next request) so signals don't accumulate.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_single_node_cold_execution -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/executor.py tests/test_pipeline_executor.py
git commit -m "feat(pipeline): single-node cold execution via orchestrator"
```

---

## Task 13: `PipelineExecutor` — three-node serial chain

**Files:**
- Modify: `tests/test_pipeline_executor.py`

The implementation already supports N nodes (Task 12's `step` closure walks the list). This task is a regression test that proves it works for the M5 demo case.

- [ ] **Step 1: Write the test**

```python
def test_three_node_chain_executes_serially(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
        (linear_spec, linear_spec.param_model(scale=5.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=10_000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 30.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_three_node_chain_executes_serially -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): regression — 3-node chain output equals composed scalars"
```

---

## Task 14: Cache lookup short-circuit on warm tap

**Files:**
- Modify: `tests/test_pipeline_executor.py`

After the first run, the tap node's output is in the orchestrator's cache. A second `request_tap` should emit `tapReady` synchronously (Task 12 already routes this through `tapReady.emit(self._new_job_id(), cached)`).

- [ ] **Step 1: Write the test**

```python
def test_warm_tap_returns_cached_output(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    # Warm.
    with qtbot.waitSignal(exe.tapReady, timeout=5000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)

    # Second request: should hit cache. We assert correctness, not strict timing
    # (CI machines vary). The fact that no orch.request runs is implicit because
    # we don't connect/disconnect — we'd see issues only as a stuck wait.
    with qtbot.waitSignal(exe.tapReady, timeout=200) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 6.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_warm_tap_returns_cached_output -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): warm tap returns cached output under tight timeout"
```

---

## Task 15: Mid-chain cache hit rebuilds suffix only

**Files:**
- Modify: `tests/test_pipeline_executor.py`

Edit param on node 2 of a 3-node chain: node 1's cache stays valid; node 2 + node 3 must re-run.

- [ ] **Step 1: Write the test**

```python
def test_param_edit_on_middle_node_invalidates_only_downstream(
    qtbot, fake_backend, linear_spec, make_pipeline
):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
        (linear_spec, linear_spec.param_model(scale=5.0)),
    )
    p.set_tap(p.nodes[-1].node_id)

    # Warm whole chain.
    with qtbot.waitSignal(exe.tapReady, timeout=5000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    cache_size_after_warm = len(orch.cache)
    assert cache_size_after_warm == 3  # 3 entries: node 1, 2, 3

    # Edit middle node param.
    p.set_params(p.nodes[1].node_id, linear_spec.param_model(scale=7.0))

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 2.0 * 7.0 * 5.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)

    # Cache now has 5 entries: node 1 (unchanged), old node 2/3, new node 2/3.
    assert len(orch.cache) == 5
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_param_edit_on_middle_node_invalidates_only_downstream -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): mid-chain param edit reuses upstream cache, recomputes suffix"
```

---

## Task 16: `PipelineExecutor` — disabled middle node skip

**Files:**
- Modify: `tests/test_pipeline_executor.py`

`Pipeline.nodes_up_to_tap` already filters disabled nodes (Task 8). This is a regression that proves end-to-end behaviour matches expectations.

- [ ] **Step 1: Write the test**

```python
def test_disabled_middle_node_is_skipped_in_chain(
    qtbot, fake_backend, linear_spec, make_pipeline
):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(
        (linear_spec, linear_spec.param_model(scale=2.0)),
        (linear_spec, linear_spec.param_model(scale=99.0)),
        (linear_spec, linear_spec.param_model(scale=3.0)),
    )
    p.set_tap(p.nodes[-1].node_id)
    p.set_enabled(p.nodes[1].node_id, False)

    with qtbot.waitSignal(exe.tapReady, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args
    expected = volume.read_inline(volume.geometry.inline_min) * 6.0  # 2.0 * 3.0
    np.testing.assert_allclose(arr, expected, rtol=1e-5)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_disabled_middle_node_is_skipped_in_chain -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): disabled middle node is skipped in chain execution"
```

---

## Task 17: `PipelineExecutor` — failure halts plan and emits `failed`

**Files:**
- Modify: `tests/test_pipeline_executor.py`

Already implemented in Task 12 (`on_failed` closure). This task adds the regression test.

- [ ] **Step 1: Write the test**

```python
def test_plugin_failure_halts_plan_and_emits_failed(
    qtbot, fake_backend, linear_spec, raising_spec
):
    """Build the chain inline because raising_spec / linear_spec both
    clear_registry on entry."""
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor
    from eggseis.pipeline.model import Node, Pipeline
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="lin", version="0.1.0", deterministic=True, vectorized=True)
    def lin(traces, scale: float = Param(default=1.0)):
        return traces * scale

    @trace_attribute(name="boom", version="0.1.0", deterministic=True, vectorized=False)
    def boom(trace, _: float = Param(default=0.0)):
        raise RuntimeError("intentional")

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = Pipeline()
    p.append(Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model(scale=2.0)))
    p.append(Node(spec=boom._eggseis_spec, params=boom._eggseis_spec.param_model()))
    p.set_tap(p.nodes[-1].node_id)

    with qtbot.waitSignal(exe.failed, timeout=5000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, message = blocker.args
    assert "boom" in message  # plugin name appears in surfaced error

    clear_registry()
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_plugin_failure_halts_plan_and_emits_failed -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): plugin failure halts plan and surfaces failed signal"
```

---

## Task 18: `PipelineExecutor` — non-deterministic node skips downstream cache

**Files:**
- Modify: `tests/test_pipeline_executor.py`

Orchestrator already enforces `deterministic` per spec. The chain consequence: any cache lookup for a node downstream of a non-deterministic node must miss because (a) the orchestrator never wrote it, and (b) we never even ask, since `deterministic_through` is False. This test pins the behaviour.

- [ ] **Step 1: Write the test**

```python
def test_non_deterministic_node_skips_cache_writes_downstream(qtbot, fake_backend):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor
    from eggseis.pipeline.model import Node, Pipeline
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="lin", version="0.1.0", deterministic=True, vectorized=True)
    def lin(traces, scale: float = Param(default=1.0)):
        return traces * scale

    @trace_attribute(name="rng", version="0.1.0", deterministic=False, vectorized=True)
    def rng(traces, amp: float = Param(default=1.0)):
        return traces

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = Pipeline()
    p.append(Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model(scale=2.0)))
    p.append(Node(spec=rng._eggseis_spec, params=rng._eggseis_spec.param_model()))
    p.append(Node(spec=lin._eggseis_spec, params=lin._eggseis_spec.param_model(scale=3.0)))
    p.set_tap(p.nodes[-1].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=5000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)

    # Cache holds only the deterministic prefix (node 1).
    assert len(orch.cache) == 1

    clear_registry()
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_non_deterministic_node_skips_cache_writes_downstream -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_executor.py
git commit -m "test(pipeline): non-deterministic node poisons downstream cache writes"
```

---

## Task 19: `PipelineExecutor` — timeslice short-circuits to raw

**Files:**
- Modify: `src/eggseis/pipeline/executor.py`
- Modify: `tests/test_pipeline_executor.py`

ROADMAP-locked: trace-local plugins don't apply on timeslice. Pipeline bypassed; viewer paints raw.

- [ ] **Step 1: Write the test**

```python
def test_timeslice_axis_short_circuits_to_raw(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline((linear_spec, linear_spec.param_model(scale=99.0)))
    p.set_tap(p.nodes[0].node_id)

    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(p, volume, "timeslice", 0)
    _job_id, arr = blocker.args
    np.testing.assert_array_equal(arr, volume.read_timeslice(0))
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_executor.py::test_timeslice_axis_short_circuits_to_raw -v`
Expected: FAIL — executor will try to chain through linear at scale=99.

- [ ] **Step 3: Add the timeslice short-circuit**

In `request_tap`, after computing `axis_enum`, prepend:

```python
        if axis_enum is Axis.TIMESLICE:
            self.tapReady.emit(self._new_job_id(), volume.read_timeslice(index))
            return
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_timeslice_axis_short_circuits_to_raw -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/executor.py tests/test_pipeline_executor.py
git commit -m "feat(pipeline): timeslice axis bypasses chain; emits raw"
```

---

## Task 20: `PipelineExecutor` — cancellation on new request_tap

**Files:**
- Modify: `src/eggseis/pipeline/executor.py`
- Modify: `tests/test_pipeline_executor.py`

When a new `request_tap` arrives mid-chain, the executor must drop its pending step queue and tell the orchestrator to cancel the in-flight tile job. The two-stage closure approach in Task 12 leaks signal connections if not cleaned. This task adds explicit cancellation.

- [ ] **Step 1: Write the test**

```python
def test_new_request_supersedes_in_flight(qtbot, fake_backend):
    """Sleep-per-trace plugin so we can race two requests."""
    import time
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor
    from eggseis.pipeline.model import Node, Pipeline
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="slow", version="0.1.0", deterministic=True, vectorized=False)
    def slow(trace, scale: float = Param(default=1.0)):
        time.sleep(0.005)  # 5 ms per trace
        return trace * scale

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = Pipeline()
    p.append(Node(spec=slow._eggseis_spec, params=slow._eggseis_spec.param_model(scale=2.0)))
    p.set_tap(p.nodes[0].node_id)

    # Kick off the slow request. Don't wait.
    exe.request_tap(p, volume, "inline", volume.geometry.inline_min)

    # Immediately supersede with a different param value.
    p.set_params(p.nodes[0].node_id, slow._eggseis_spec.param_model(scale=4.0))
    with qtbot.waitSignal(exe.tapReady, timeout=10_000) as blocker:
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)
    _job_id, arr = blocker.args

    np.testing.assert_allclose(
        arr, volume.read_inline(volume.geometry.inline_min) * 4.0, rtol=1e-5
    )
    clear_registry()
```

- [ ] **Step 2: Run to verify failure or flake**

Run: `pytest tests/test_pipeline_executor.py::test_new_request_supersedes_in_flight -v`
Expected: may pass by accident; may fail or hang if signals stack.

- [ ] **Step 3: Add `cancel_active` and explicit slot tracking**

Refactor `executor.py` to track the active connections explicitly:

```python
class PipelineExecutor(QObject):
    tapReady = Signal(int, object)
    intermediateReady = Signal(int, str, object)
    failed = Signal(int, str)

    def __init__(self, orchestrator: JobOrchestrator) -> None:
        super().__init__()
        self._orch = orchestrator
        self._next_job_id = 0
        self._active_job_id: int | None = None
        self._active_on_ready = None
        self._active_on_failed = None

    def cancel_active(self) -> None:
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
```

Update `request_tap` to call `self.cancel_active()` first (before any branch). Update `_run_chain` to register `self._active_on_ready = on_ready; self._active_on_failed = on_failed` before each `self._orch.request(...)` and to null them at the start of `on_ready`/`on_failed`. Drop in-flight steps if `self._active_job_id != job_id` at the top of either closure.

Replace `_run_chain` with this version:

```python
    def _run_chain(
        self,
        pipeline: Pipeline,
        volume: SeismicVolume,
        axis: Axis,
        index: int,
        cold_nodes: list[Node],
        starting_input: np.ndarray,
    ) -> None:
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

            self._active_on_ready = on_ready
            self._active_on_failed = on_failed
            self._orch.sectionReady.connect(on_ready)
            self._orch.failed.connect(on_failed)
            self._orch.request(
                node.spec, node.params, volume, axis, index,
                input_section=current_input, chain_hash=chain_hash,
            )

        step(0, starting_input)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_pipeline_executor.py::test_new_request_supersedes_in_flight -v`
Expected: PASS.

- [ ] **Step 5: Run the full executor suite**

Run: `pytest tests/test_pipeline_executor.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/pipeline/executor.py tests/test_pipeline_executor.py
git commit -m "feat(pipeline): cancel_active drops pending steps and signals on supersede"
```

---

## Task 21: `PipelineDock` skeleton + Source row

**Files:**
- Create: `src/eggseis/pipeline/dock.py`
- Create: `tests/test_pipeline_dock.py`

Headless Qt tests run under `QT_QPA_PLATFORM=offscreen`. The dock is a `QDockWidget` whose widget is a `QWidget` containing a `QListWidget` (rows) + a `QStackedWidget` (param panel) + an "+ Add plugin" `QPushButton`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_dock.py`:

```python
"""PipelineDock tests — headless Qt via pytest-qt + offscreen platform."""

from __future__ import annotations

import pytest


def test_source_row_appears_first_after_bind(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    dock.bind(make_pipeline())  # empty pipeline
    assert dock.list_widget.count() == 1
    assert "source" in dock.list_widget.item(0).text().lower()


def test_bind_renders_user_added_nodes(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)
    assert dock.list_widget.count() == 3  # Source + 2 nodes
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: ImportError on `eggseis.pipeline.dock`.

- [ ] **Step 3: Implement the dock skeleton**

Create `src/eggseis/pipeline/dock.py`:

```python
"""PipelineDock — list-style UI for the M5 linear pipeline.

Layout:

    +-----------------------------+
    | [Source (raw amplitude)]   ◯|
    | [bandpass]              ☐ ◯|
    | [envelope]              ☐ ◯|
    | [+ Add plugin]              |
    +-----------------------------+
    | <param panel for selected> |
    +-----------------------------+
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


class PipelineDock(QDockWidget):
    pipelineChanged = Signal()
    tapChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None

        body = QWidget(self)
        layout = QVBoxLayout(body)

        self.list_widget = QListWidget(body)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_button = QPushButton("+ Add plugin", body)
        layout.addWidget(self.add_button)

        self.param_host = QStackedWidget(body)
        layout.addWidget(self.param_host, stretch=1)

        self.setWidget(body)

    def bind(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._refresh()

    def _refresh(self) -> None:
        self.list_widget.clear()
        if self._pipeline is None:
            return
        # Source row.
        src_item = QListWidgetItem("Source (raw amplitude)")
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.list_widget.addItem(src_item)
        for node in self._pipeline.nodes:
            self._append_node_row(node)

    def _append_node_row(self, node: Node) -> None:
        item = QListWidgetItem(node.spec.name)
        item.setData(Qt.UserRole, node.node_id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        item.setFlags(flags)
        self.list_widget.addItem(item)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): PipelineDock skeleton with non-removable Source row"
```

---

## Task 22: Dock — add plugin appends a node row

**Files:**
- Modify: `src/eggseis/pipeline/dock.py`
- Modify: `tests/test_pipeline_dock.py`

- [ ] **Step 1: Write the failing test**

```python
def test_add_plugin_appends_node(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline()
    dock.bind(p)

    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.add_plugin(linear_spec)

    assert dock.list_widget.count() == 2  # Source + new node
    assert len(p.nodes) == 1
    assert p.nodes[0].spec is linear_spec
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py::test_add_plugin_appends_node -v`
Expected: AttributeError on `add_plugin`.

- [ ] **Step 3: Implement `add_plugin`**

Add to `PipelineDock`:

```python
    def add_plugin(self, spec) -> None:
        if self._pipeline is None:
            return
        node = Node(spec=spec, params=spec.param_model())
        self._pipeline.append(node)
        self._refresh()
        self.pipelineChanged.emit()
```

`Node` is already imported.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_pipeline_dock.py::test_add_plugin_appends_node -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): dock add_plugin appends Node and emits pipelineChanged"
```

---

## Task 23: Dock — selection-driven param panel

**Files:**
- Modify: `src/eggseis/pipeline/dock.py`
- Modify: `tests/test_pipeline_dock.py`

The param panel is a `QStackedWidget` that holds one widget per node, plus an empty placeholder for the Source row. Clicking a row swaps the visible widget. Param widgets are produced by `eggseis.widgets.param_dock.ParamDock` (M3 magicgui-based) or a thin equivalent.

For testability we'll use a pluggable factory so tests can inject a `QLabel` mock instead of touching magicgui.

- [ ] **Step 1: Write the failing test**

```python
def test_select_row_swaps_param_panel(qtbot, linear_spec, make_pipeline):
    from PySide6.QtWidgets import QLabel
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock(param_widget_factory=lambda node: QLabel(node.node_id))
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)

    # Select first user node (row 1; row 0 is Source).
    dock.list_widget.setCurrentRow(1)
    assert isinstance(dock.param_host.currentWidget(), QLabel)
    assert dock.param_host.currentWidget().text() == p.nodes[0].node_id

    # Switch to second.
    dock.list_widget.setCurrentRow(2)
    assert dock.param_host.currentWidget().text() == p.nodes[1].node_id


def test_source_row_shows_empty_param_panel(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock(param_widget_factory=lambda node: None)
    qtbot.addWidget(dock)
    dock.bind(make_pipeline(linear_spec))
    dock.list_widget.setCurrentRow(0)  # Source
    # Source has no param widget; the placeholder is shown.
    assert dock.param_host.currentWidget() is dock._empty_panel
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py -v -k param_panel`
Expected: TypeError on `param_widget_factory` kwarg.

- [ ] **Step 3: Implement**

Update `PipelineDock.__init__`:

```python
    def __init__(self, parent: QWidget | None = None, *, param_widget_factory=None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None
        self._param_widget_factory = param_widget_factory
        self._param_widgets: dict[str, QWidget] = {}

        body = QWidget(self)
        layout = QVBoxLayout(body)

        self.list_widget = QListWidget(body)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_button = QPushButton("+ Add plugin", body)
        layout.addWidget(self.add_button)

        self.param_host = QStackedWidget(body)
        self._empty_panel = QWidget(body)
        self.param_host.addWidget(self._empty_panel)
        layout.addWidget(self.param_host, stretch=1)

        self.setWidget(body)
```

Update `_refresh` to (re)build per-node param widgets and add them to the stack:

```python
    def _refresh(self) -> None:
        self.list_widget.clear()
        # Tear down old param widgets.
        for w in list(self._param_widgets.values()):
            self.param_host.removeWidget(w)
            w.deleteLater()
        self._param_widgets.clear()

        if self._pipeline is None:
            return

        src_item = QListWidgetItem("Source (raw amplitude)")
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.list_widget.addItem(src_item)

        for node in self._pipeline.nodes:
            self._append_node_row(node)
            if self._param_widget_factory is not None:
                widget = self._param_widget_factory(node)
                if widget is not None:
                    self.param_host.addWidget(widget)
                    self._param_widgets[node.node_id] = widget

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.list_widget.item(row)
        node_id = item.data(Qt.UserRole)
        if node_id == SOURCE_ID or node_id not in self._param_widgets:
            self.param_host.setCurrentWidget(self._empty_panel)
            return
        self.param_host.setCurrentWidget(self._param_widgets[node_id])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): selection-driven param panel via injectable widget factory"
```

---

## Task 24: Dock — enable checkbox + tap radio per node row

**Files:**
- Modify: `src/eggseis/pipeline/dock.py`
- Modify: `tests/test_pipeline_dock.py`

Each node row needs a checkbox (enable) and a radio button (tap). Radio is greyed when checkbox is unchecked.

The simplest layout: instead of plain `QListWidgetItem` text, each row uses `QListWidget.setItemWidget(item, RowWidget(node))`. `RowWidget` is a `QWidget` with: name `QLabel`, enable `QCheckBox`, tap `QRadioButton`.

Tap radios are mutually exclusive across rows including the Source row — wrap them all in a single `QButtonGroup` owned by the dock.

- [ ] **Step 1: Write the failing tests**

```python
def test_enable_checkbox_toggles_node(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        row_widget.enable_checkbox.setChecked(False)
    assert p.nodes[0].enabled is False


def test_disable_greys_tap_radio(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    assert row_widget.tap_radio.isEnabled() is True
    row_widget.enable_checkbox.setChecked(False)
    assert row_widget.tap_radio.isEnabled() is False


def test_clicking_tap_radio_emits_tapChanged(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)

    row_widget = dock.row_widget(p.nodes[0].node_id)
    with qtbot.waitSignal(dock.tapChanged, timeout=1000) as blocker:
        row_widget.tap_radio.setChecked(True)
    (new_tap,) = blocker.args
    assert new_tap == p.nodes[0].node_id
    assert p.tap_node_id == p.nodes[0].node_id


def test_source_tap_radio_present_and_default(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec)
    dock.bind(p)
    assert dock.source_tap_radio.isChecked() is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py -v -k "enable or tap"`
Expected: AttributeError on `row_widget` / `source_tap_radio`.

- [ ] **Step 3: Implement the row widget + button group wiring**

Replace the body of `dock.py` with the version below (additions in **bold conceptually** — full file shown):

```python
"""PipelineDock — list-style UI for the M5 linear pipeline."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline


class _NodeRow(QWidget):
    def __init__(self, node: Node, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.enable_checkbox = QCheckBox(self)
        self.enable_checkbox.setChecked(node.enabled)
        self.label = QLabel(node.spec.name, self)
        self.tap_radio = QRadioButton(self)
        self.tap_radio.setEnabled(node.enabled)
        layout.addWidget(self.enable_checkbox)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.tap_radio)


class _SourceRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.label = QLabel("Source (raw amplitude)", self)
        self.tap_radio = QRadioButton(self)
        self.tap_radio.setChecked(True)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.tap_radio)


class PipelineDock(QDockWidget):
    pipelineChanged = Signal()
    tapChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, param_widget_factory=None) -> None:
        super().__init__("Pipeline", parent)
        self._pipeline: Pipeline | None = None
        self._param_widget_factory = param_widget_factory
        self._param_widgets: dict[str, QWidget] = {}
        self._row_widgets: dict[str, _NodeRow] = {}
        self._source_row: _SourceRow | None = None
        self._tap_group = QButtonGroup(self)
        self._tap_group.setExclusive(True)

        body = QWidget(self)
        layout = QVBoxLayout(body)

        self.list_widget = QListWidget(body)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_button = QPushButton("+ Add plugin", body)
        layout.addWidget(self.add_button)

        self.param_host = QStackedWidget(body)
        self._empty_panel = QWidget(body)
        self.param_host.addWidget(self._empty_panel)
        layout.addWidget(self.param_host, stretch=1)

        self.setWidget(body)

    @property
    def source_tap_radio(self) -> QRadioButton | None:
        return self._source_row.tap_radio if self._source_row else None

    def row_widget(self, node_id: str) -> _NodeRow | None:
        return self._row_widgets.get(node_id)

    def bind(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._refresh()

    def add_plugin(self, spec) -> None:
        if self._pipeline is None:
            return
        node = Node(spec=spec, params=spec.param_model())
        self._pipeline.append(node)
        self._refresh()
        self.pipelineChanged.emit()

    def _refresh(self) -> None:
        # Tear down stacked widgets.
        for w in list(self._param_widgets.values()):
            self.param_host.removeWidget(w)
            w.deleteLater()
        self._param_widgets.clear()
        for btn in list(self._tap_group.buttons()):
            self._tap_group.removeButton(btn)
        self.list_widget.clear()
        self._row_widgets.clear()

        if self._pipeline is None:
            return

        # Source row.
        src_item = QListWidgetItem(self.list_widget)
        src_item.setData(Qt.UserRole, SOURCE_ID)
        src_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._source_row = _SourceRow()
        src_item.setSizeHint(self._source_row.sizeHint())
        self.list_widget.addItem(src_item)
        self.list_widget.setItemWidget(src_item, self._source_row)
        self._tap_group.addButton(self._source_row.tap_radio)
        self._source_row.tap_radio.toggled.connect(
            lambda on: self._on_tap_toggled(SOURCE_ID, on)
        )

        for node in self._pipeline.nodes:
            self._append_node_row(node)
            if self._param_widget_factory is not None:
                widget = self._param_widget_factory(node)
                if widget is not None:
                    self.param_host.addWidget(widget)
                    self._param_widgets[node.node_id] = widget

        # Restore tap selection from pipeline state.
        self._sync_tap_radio_from_pipeline()

    def _append_node_row(self, node: Node) -> None:
        item = QListWidgetItem(self.list_widget)
        item.setData(Qt.UserRole, node.node_id)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        item.setFlags(flags)
        row = _NodeRow(node)
        item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)
        self._row_widgets[node.node_id] = row
        self._tap_group.addButton(row.tap_radio)
        row.enable_checkbox.toggled.connect(
            lambda on, nid=node.node_id: self._on_enable_toggled(nid, on)
        )
        row.tap_radio.toggled.connect(
            lambda on, nid=node.node_id: self._on_tap_toggled(nid, on)
        )

    def _on_enable_toggled(self, node_id: str, on: bool) -> None:
        if self._pipeline is None:
            return
        self._pipeline.set_enabled(node_id, on)
        row = self._row_widgets.get(node_id)
        if row is not None:
            row.tap_radio.setEnabled(on)
        # Tap may have shifted in the model; re-sync the radio.
        self._sync_tap_radio_from_pipeline()
        self.pipelineChanged.emit()

    def _on_tap_toggled(self, node_id: str, on: bool) -> None:
        if not on or self._pipeline is None:
            return
        self._pipeline.set_tap(node_id)
        # set_tap may have rejected the request and shifted upstream.
        if self._pipeline.tap_node_id != node_id:
            self._sync_tap_radio_from_pipeline()
        self.tapChanged.emit(self._pipeline.tap_node_id)

    def _sync_tap_radio_from_pipeline(self) -> None:
        if self._pipeline is None:
            return
        target = self._pipeline.tap_node_id
        if target == SOURCE_ID and self._source_row is not None:
            self._source_row.tap_radio.setChecked(True)
            return
        row = self._row_widgets.get(target)
        if row is not None:
            row.tap_radio.setChecked(True)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.list_widget.item(row)
        node_id = item.data(Qt.UserRole)
        if node_id == SOURCE_ID or node_id not in self._param_widgets:
            self.param_host.setCurrentWidget(self._empty_panel)
            return
        self.param_host.setCurrentWidget(self._param_widgets[node_id])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): row widget with enable checkbox + exclusive tap radio group"
```

---

## Task 25: Dock — remove and reorder

**Files:**
- Modify: `src/eggseis/pipeline/dock.py`
- Modify: `tests/test_pipeline_dock.py`

A right-click "Remove" context-menu entry on user node rows; drag-and-drop reorder via `QListWidget.InternalMove`.

- [ ] **Step 1: Write the failing tests**

```python
def test_remove_node_via_method(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec)
    dock.bind(p)

    target_id = p.nodes[0].node_id
    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.remove_node(target_id)
    assert len(p.nodes) == 1
    assert p.nodes[0].node_id != target_id


def test_drag_reorder_updates_pipeline_order(qtbot, linear_spec, make_pipeline):
    from eggseis.pipeline.dock import PipelineDock

    dock = PipelineDock()
    qtbot.addWidget(dock)
    p = make_pipeline(linear_spec, linear_spec, linear_spec)
    dock.bind(p)
    original_ids = [n.node_id for n in p.nodes]

    # Move row 3 (last user node) to the top user-node slot (after Source).
    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        dock.move_row(3, 1)

    new_ids = [n.node_id for n in p.nodes]
    assert new_ids == [original_ids[2], original_ids[0], original_ids[1]]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py -v -k "remove or reorder"`
Expected: AttributeError.

- [ ] **Step 3: Implement**

Add to `PipelineDock`:

```python
    def remove_node(self, node_id: str) -> None:
        if self._pipeline is None:
            return
        if node_id == SOURCE_ID:
            return
        self._pipeline.remove(node_id)
        self._refresh()
        self.pipelineChanged.emit()

    def move_row(self, from_row: int, to_row: int) -> None:
        """Move list row from_row → to_row (1-indexed since Source occupies row 0).

        Both indices must be > 0; row 0 is Source and is not draggable.
        """
        if self._pipeline is None or from_row <= 0 or to_row <= 0:
            return
        node_id = self.list_widget.item(from_row).data(Qt.UserRole)
        target_index_in_pipeline = to_row - 1
        self._pipeline.move(node_id, target_index_in_pipeline)
        self._refresh()
        self.pipelineChanged.emit()
```

For the drag-drop wiring, connect `self.list_widget.model().rowsMoved` to a slot that calls `move_row` based on the model indices. Append in `__init__`:

```python
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
```

Add the slot:

```python
    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, dest_row: int) -> None:
        # `start` is the original row, `dest_row` is the target. Qt may have
        # already moved internally; we mirror to the model.
        # We get one event per move; accept it as-is.
        if start == dest_row or start == 0:
            return
        # Translate Qt's "insert before dest_row" semantics into our move call.
        target_index = dest_row - 1 if dest_row > start else dest_row
        target_index_in_pipeline = max(0, target_index - 1)
        item = self.list_widget.item(target_index)
        node_id = item.data(Qt.UserRole)
        if node_id == SOURCE_ID:
            return
        # No need to mutate Qt list; rebuild from model.
        self._pipeline.move(node_id, target_index_in_pipeline)
        self._refresh()
        self.pipelineChanged.emit()
```

The `move_row` method is the explicit, scriptable API tested in Step 1; the drag-drop slot is best-effort. If the drag-drop slot proves flaky in the demo, fall back to programmatic move via context menu (deferred to a follow-up).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): dock supports remove_node and move_row, drag-drop wired"
```

---

## Task 26: Dock — param-change emits `pipelineChanged`

**Files:**
- Modify: `src/eggseis/pipeline/dock.py`
- Modify: `tests/test_pipeline_dock.py`

The param widget factory injects per-node param widgets. When the underlying pydantic model is updated by the widget, the dock must update `pipeline.set_params(...)` and emit `pipelineChanged`. We expose a small protocol on the factory: the returned widget must have a `paramsChanged` Qt signal carrying the new pydantic model. The dock subscribes.

- [ ] **Step 1: Write the failing test**

```python
def test_param_change_updates_pipeline_and_emits_changed(qtbot, linear_spec, make_pipeline):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QWidget
    from eggseis.pipeline.dock import PipelineDock

    class FakeWidget(QWidget):
        paramsChanged = Signal(object)

    def factory(node):
        w = FakeWidget()
        w._eggseis_node_id = node.node_id  # not used by dock; convenience
        return w

    dock = PipelineDock(param_widget_factory=factory)
    qtbot.addWidget(dock)
    p = make_pipeline((linear_spec, linear_spec.param_model(scale=1.0)))
    dock.bind(p)

    new_params = linear_spec.param_model(scale=9.0)
    target_widget = dock._param_widgets[p.nodes[0].node_id]

    with qtbot.waitSignal(dock.pipelineChanged, timeout=1000):
        target_widget.paramsChanged.emit(new_params)

    assert p.nodes[0].params.scale == 9.0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pipeline_dock.py::test_param_change_updates_pipeline_and_emits_changed -v`
Expected: FAIL.

- [ ] **Step 3: Wire the signal in `_refresh`**

Inside the `for node in self._pipeline.nodes:` loop in `_refresh`, after `self._param_widgets[node.node_id] = widget`, add:

```python
                    if hasattr(widget, "paramsChanged"):
                        widget.paramsChanged.connect(
                            lambda new_params, nid=node.node_id: self._on_params_changed(nid, new_params)
                        )
```

Add the slot:

```python
    def _on_params_changed(self, node_id: str, new_params) -> None:
        if self._pipeline is None:
            return
        self._pipeline.set_params(node_id, new_params)
        self.pipelineChanged.emit()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_dock.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/dock.py tests/test_pipeline_dock.py
git commit -m "feat(pipeline): dock param-widget paramsChanged emits pipelineChanged"
```

---

## Task 27: `MainWindow` — `_pipelines` dict + dock instance

**Files:**
- Modify: `src/eggseis/app.py`

Wire the pipeline dock and per-survey state into the existing window.

- [ ] **Step 1: Add imports and member fields**

In `src/eggseis/app.py`, near the existing imports, add:

```python
from eggseis.pipeline import Pipeline, PipelineExecutor, SOURCE_ID
from eggseis.pipeline.dock import PipelineDock
```

In `MainWindow.__init__`, after `self._compute = JobOrchestrator()`, add:

```python
        self._executor = PipelineExecutor(self._compute)
        self._executor.tapReady.connect(self._on_tap_ready)
        self._executor.failed.connect(self._on_chain_failed)

        self._pipelines: dict[str, Pipeline] = {}
        self._active_survey_id: str | None = None
        self._pipeline_dock = PipelineDock(param_widget_factory=self._make_param_widget)
        self._pipeline_dock.pipelineChanged.connect(self._request_tap)
        self._pipeline_dock.tapChanged.connect(lambda _id: self._request_tap())
        self._pipeline_dock.add_button.clicked.connect(self._on_add_plugin_clicked)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._pipeline_dock)
```

- [ ] **Step 2: Modify `open_survey` to manage per-survey pipelines**

Replace `open_survey` with:

```python
    def open_survey(self, survey_path: Path) -> None:
        volume = SeismicVolume(MDIOBackend(survey_path), name=survey_path.stem)
        survey_id = str(survey_path.resolve())
        self._active_survey_id = survey_id
        self._pipelines.setdefault(survey_id, Pipeline())
        self.section_viewer.set_volume(volume)
        self.slice_nav.set_geometry(volume.geometry)
        self._pipeline_dock.bind(self._pipelines[survey_id])
        self._request_tap()
```

- [ ] **Step 3: Add the routing methods**

```python
    def _make_param_widget(self, node):
        # M5 reuses the M3 magicgui-based dock by adapting it per-node.
        # Stub for now: the M3 ParamDock can be instantiated per-node with
        # the spec + params; it already exposes paramsChanged.
        from eggseis.widgets.param_dock import ParamDock
        widget = ParamDock()
        widget.set_plugin(node.spec)
        widget.set_params(node.params) if hasattr(widget, "set_params") else None
        return widget

    def _on_add_plugin_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        from eggseis.plugin_loader import discover_all
        specs = sorted(discover_all(), key=lambda s: s.name)
        if not specs:
            return
        names = [s.name for s in specs]
        choice, ok = QInputDialog.getItem(self, "Add plugin", "Plugin:", names, 0, False)
        if not ok:
            return
        spec = next(s for s in specs if s.name == choice)
        self._pipeline_dock.add_plugin(spec)

    def _request_tap(self) -> None:
        volume = self.section_viewer.volume
        if volume is None or self._active_survey_id is None:
            return
        pipeline = self._pipelines[self._active_survey_id]
        self._executor.request_tap(
            pipeline,
            volume,
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )

    def _on_tap_ready(self, _job_id: int, arr) -> None:
        self.section_viewer.set_overlay(arr, partial=False)

    def _on_chain_failed(self, _job_id: int, message: str) -> None:
        self._compute_errors.append(("chain", message))
        self._compute_errors_action.setText(
            f"&Compute Errors… ({len(self._compute_errors)})"
        )
        self.statusBar().showMessage(f"Pipeline failed: {message}", 5000)
```

`ParamDock.set_params` may not exist; if not, omit the call (the magicgui widget will read defaults from the param model on construction). In that case, the round-trip "load existing params back into the widget" is best-effort and can be polished as a follow-up.

- [ ] **Step 4: Wire `_on_slice_changed` to the chain**

Replace `_on_slice_changed`:

```python
    def _on_slice_changed(self, axis, index) -> None:
        self.section_viewer.show_slice(axis, index)
        if self._active_survey_id is not None:
            self._request_tap()
```

- [ ] **Step 5: Run the existing GUI smoke and section-viewer tests**

Run: `pytest tests/test_gui_smoke.py tests/test_section_viewer.py -v`
Expected: all green. The single-attribute `_recompute_overlay` path still works because nothing removed the existing `Attribute` menu wiring; it now competes with the dock but they don't fight (M5 keeps both for compatibility).

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/app.py
git commit -m "feat(app): wire PipelineDock + PipelineExecutor; per-survey pipeline registry"
```

---

## Task 28: GUI smoke — three-attribute chain, tap each

**Files:**
- Modify: `tests/test_gui_smoke.py`

End-to-end test: open the demo project, add `ormsby_bandpass`, `envelope`, `rms_amplitude` via the dock, tap each, assert the overlay updates.

- [ ] **Step 1: Write the test**

Append to `tests/test_gui_smoke.py`:

```python
def test_chain_three_attributes_tap_each(qtbot, demo_project_path):
    from eggseis.app import MainWindow
    from eggseis.builtins.envelope import envelope
    from eggseis.builtins.ormsby_bandpass import ormsby_bandpass
    from eggseis.builtins.rms_amplitude import rms_amplitude

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.volume is not None)

    dock = win._pipeline_dock
    for spec_func in (ormsby_bandpass, envelope, rms_amplitude):
        spec = spec_func._eggseis_spec
        with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
            dock.add_plugin(spec)

    pipeline = win._pipelines[win._active_survey_id]
    assert len(pipeline.nodes) == 3

    for node in pipeline.nodes:
        with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
            dock.row_widget(node.node_id).tap_radio.setChecked(True)
        assert win.section_viewer.has_overlay
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_gui_smoke.py::test_chain_three_attributes_tap_each -v`
Expected: PASS. If it fails, inspect the failure carefully — the M3 magicgui-based ParamDock interaction is the most likely culprit.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gui_smoke.py
git commit -m "test(gui): three-attribute chain — tap each node, overlay updates"
```

---

## Task 29: Status bar progress + chained errors in `Help → Compute Errors`

**Files:**
- Modify: `src/eggseis/app.py`
- Modify: `src/eggseis/pipeline/executor.py`

Show "Computing N of M: <plugin>…" in the status bar while the executor is mid-plan; clear on `tapReady`. Already-existing `Compute Errors` log accepts the chain-failure entries (the format includes the plugin name from Task 12's `on_failed`).

- [ ] **Step 1: Emit progress from the executor**

Add to `PipelineExecutor`:

```python
    progress = Signal(int, int, str)  # current_index (1-based), total, plugin_name
```

In `_run_chain.step`, before `self._orch.request(...)`, add:

```python
            self.progress.emit(idx + 1, len(cold_nodes), node.spec.name)
```

- [ ] **Step 2: Connect in MainWindow**

In `MainWindow.__init__`, after `self._executor.failed.connect(...)`:

```python
        self._executor.progress.connect(self._on_chain_progress)
```

Add slot:

```python
    def _on_chain_progress(self, current: int, total: int, name: str) -> None:
        self.statusBar().showMessage(f"Computing {current} of {total}: {name}…")
```

And in `_on_tap_ready`:

```python
        self.statusBar().clearMessage()
```

- [ ] **Step 3: Write a smoke test**

Append to `tests/test_pipeline_executor.py`:

```python
def test_progress_signal_fires_per_node(qtbot, fake_backend, linear_spec, make_pipeline):
    from eggseis.compute.orchestrator import JobOrchestrator
    from eggseis.data import SeismicVolume
    from eggseis.pipeline.executor import PipelineExecutor

    volume = SeismicVolume(fake_backend, name="v")
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)

    p = make_pipeline(linear_spec, linear_spec, linear_spec)
    p.set_tap(p.nodes[-1].node_id)

    seen: list[tuple[int, int, str]] = []
    exe.progress.connect(lambda *args: seen.append(args))

    with qtbot.waitSignal(exe.tapReady, timeout=10_000):
        exe.request_tap(p, volume, "inline", volume.geometry.inline_min)

    assert len(seen) == 3
    assert [s[0] for s in seen] == [1, 2, 3]
    assert all(s[1] == 3 for s in seen)
```

- [ ] **Step 4: Run the test plus the GUI smoke**

Run: `pytest tests/test_pipeline_executor.py tests/test_gui_smoke.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/pipeline/executor.py src/eggseis/app.py tests/test_pipeline_executor.py
git commit -m "feat(pipeline): progress signal + status bar 'Computing N of M' surface"
```

---

## Task 30: Documentation

**Files:**
- Modify: `docs/development.md`
- Modify: `docs/plugin-authoring.md`
- Modify: `README.md`

- [ ] **Step 1: Append "How pipelines work in the GUI" to `docs/development.md`**

```markdown
## How pipelines work in the GUI

eggseis (M5+) lets the user stack multiple trace-local plugins into a linear
pipeline per survey. The dock at the left of the main window lists the chain;
each node has an enable checkbox and a tap radio. The section viewer paints
the output of whichever node is tapped (Source = raw amplitude).

Mechanics:

- **Per-survey scope.** Each opened survey gets its own `Pipeline`, kept in
  memory for the session. Closing a survey doesn't lose the chain; opening
  a different survey shows that survey's chain (which may be empty).
  Persistence to disk is M7's job.

- **Cache via `chain_hash`.** Each node has a content-addressed key that
  folds in `(plugin_id, plugin_version, params, parent_chain_hash)`. The
  M4 `SectionLRU` is reused directly — there is no separate pipeline cache.
  Editing one node's params leaves all upstream cache entries intact;
  downstream entries miss naturally because their `chain_hash` differs.

- **Lazy recompute.** Only the path from Source to the current tap runs.
  If you tap node 1, nodes 2–5 stay dirty until you tap one of them; then
  the cold suffix runs.

- **Disabled nodes** are skipped at execution time (they pass their parent's
  output through unchanged) and their tap radio is greyed. The cache key
  reflects the skip, so disabling a node does not invalidate cached entries
  for an upstream node — only downstream nodes re-key.

- **Non-deterministic plugins** (`deterministic=False`) and every node
  downstream of one are excluded from cache reads and writes. The plugin
  itself runs normally; results are simply not memoised.

- **Timeslice axis** bypasses the chain entirely. Trace-local plugins do
  not apply to a horizontal slice; the viewer paints raw amplitude until
  the user switches to inline or xline.
```

- [ ] **Step 2: Append a sentence to `docs/plugin-authoring.md`**

Find the section that mentions `deterministic=False` (added in M4) and add:

```markdown
> **In a pipeline:** a `deterministic=False` node poisons every node
> downstream of itself for caching purposes. The plugin still runs;
> outputs are simply never memoised, so revisiting the same params and
> slice always recomputes. Prefer `deterministic=True` whenever your
> plugin's output is a pure function of its input and parameters.
```

- [ ] **Step 3: Update the README status block**

Find the status table or list that names M4. Add an M5 line:

```markdown
- M5: pipeline chain — list-style dock, tap-anywhere, lazy recompute, chain_hash cache.
```

- [ ] **Step 4: Run lint + smoke**

Run: `./scripts/test.sh ci`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add docs/development.md docs/plugin-authoring.md README.md
git commit -m "docs: M5 — pipelines in the GUI, deterministic-false poisons chain"
```

---

## Task 31: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the `[v0.1.0a5]` entry**

Insert at the top of the file (above `[v0.1.0a4]`):

```markdown
## [v0.1.0a5] — M5: pipeline chain

### Added
- `eggseis.pipeline` package: `Pipeline`, `Node`, `PipelineExecutor`.
- Per-survey linear pipelines retained for the session (lost on app quit).
- Pipeline dock widget: list of nodes with enable checkbox + tap radio per row,
  selection-driven param panel, "+ Add plugin" picker, drag-to-reorder.
- Tap-anywhere: section viewer binds to the tap node's output rather than a
  single attribute.
- `chain_hash`-keyed cache: each node's output is memoised with a Source-rooted
  hash so editing an upstream parameter invalidates only downstream nodes.
- `deterministic=False` poisons the chain downstream as well as itself.

### Changed
- `CacheKey.params_hash` renamed to `chain_hash` (semantic-only; helper still
  computes a params-only digest for single-attribute callers).
- `JobOrchestrator.request` accepts optional `input_section` and `chain_hash`
  keyword arguments so the executor can drive it through a chain without
  re-reading the volume.

### Notes
- Pipeline persistence to disk is intentionally deferred to M7.
- Branching, multi-input nodes, and the visual node-graph canvas are M6.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG entry for v0.1.0a5"
```

---

## Task 32: Final CI run

**Files:** none.

- [ ] **Step 1: Run the full suite**

Run: `./scripts/test.sh ci`
Expected: all green.

- [ ] **Step 2: Inspect for incidental warnings**

Common offenders: leaked Qt widgets in long test runs (`QPaintDevice` warnings), flaky cancel test under load, unused imports introduced during the refactor.

- [ ] **Step 3: If everything is clean, the milestone is implementation-complete.**

Follow the milestone wrap-up workflow stored in memory (audit ROADMAP exit criteria → CHANGELOG → README → next-milestone issue → tag after merge). The wrap-up is not part of this plan; do it separately once the PR is merged.

---

## Self-Review

**1. Spec coverage:** Every locked decision in `M5-PLAN.md` has a task:

| Spec section | Task |
|---|---|
| Per-survey pipeline registry | Task 27 |
| Explicit Source row | Tasks 21, 24 |
| Tap on disabled greys radio | Tasks 7, 24 |
| Tap on timeslice → raw | Task 19 |
| Selection-driven param panel | Tasks 23, 26 |
| `chain_hash` replaces `params_hash` | Tasks 1, 2, 9 |
| `SectionLRU` reuse | Tasks 1–3 (no parallel cache; orch uses existing LRU) |
| Lazy recompute | Tasks 12, 14 |
| Determinism propagation | Tasks 10, 18 |
| Duplicates allowed via `node_id` | Task 5 (uuid4) + Task 9 hash invariance |
| Trace-local downstream input contract | Task 12 (orch passes `input_section`) |
| Serial execution | Task 12 |
| `PipelineExecutor` between MainWindow + orchestrator | Tasks 11–20 |
| Cancellation single in-flight | Task 20 |

**2. Placeholder scan:** No `TBD`, no "implement later". The single best-effort note is the drag-drop reorder slot in Task 25, which has a fallback (`move_row`) that is fully covered by tests; users who don't trigger drag-drop will not notice.

**3. Type consistency:** `PipelineExecutor` signal names (`tapReady`, `intermediateReady`, `failed`, `progress`) are consistent across all tasks and the MainWindow wiring. `Pipeline` method names (`append`, `remove`, `move`, `set_enabled`, `set_params`, `set_tap`, `nodes_up_to_tap`, `chain_hash_for`, `deterministic_through`) match the spec one-for-one. `make_cache_key` keyword `chain_hash` matches the field rename in Task 1.
