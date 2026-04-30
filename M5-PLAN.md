# M5 — "The pipeline chains"

**Milestone 5 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M4-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Stack two or more attributes on a survey, inspect the data at any node in the chain, edit a node's parameters and watch only the dirty downstream segment recompute. The user assembles `bandpass → envelope → rms_amplitude`, taps each node in turn, and the section viewer paints that node's output. Editing the bandpass parameters invalidates envelope and rms but leaves the bandpass cache intact for any other slice/tap that revisits the same params.

This is the milestone where plugins stop being one-shot effects and become a workflow. The dock-style list UI shipped here is the same UX shape M6 will replace with a visual node graph; the cache key chain shipped here is the same key chain M6 will extend to multi-input ports. Both are intentional bridges.

## Exit criteria

You're done with M5 when this is true:

- Build a 3-node chain (`bandpass → envelope → rms_amplitude`) on the F3 fragment; tap each node; section viewer shows that node's output.
- Edit `bandpass` parameters: nodes 2 and 3 recompute, node 1's prior outputs evicted only if they fall out of LRU; revisiting old params for node 1 hits cache.
- Disable the middle node: chain skips it, downstream recomputes against the upstream output, tap radio on the disabled node is greyed.
- Tap switch on a cache-warm node paints in **<50 ms** (inherits M4 cache hit budget).
- Cache key chain works: each node's entry is keyed by `(plugin_id, plugin_version, params_hash, parent_chain_hash, axis, index, volume_version)`. Reuses M4's `SectionLRU` directly; no parallel cache.
- Non-deterministic plugin in the middle of the chain: nothing from that node down is cached; nodes above it are cached normally.
- Headless tests cover chain semantics, cache hit/miss, parameter-edit invalidates downstream only, tap-anywhere produces correct intermediate, disabled-node skip semantics, plugin-removed orphan handling.
- `eggseis info` and `eggseis dump-inline` unchanged. Compute engine remains a GUI concern; library/CLI keep their synchronous `run_on_section`.
- Per-survey pipeline retained for the session: close a survey, reopen it, the chain is still there. Lost on app quit (M7 owns project save).

---

## Locked design decisions for M5

| Area | Decision |
|---|---|
| Pipeline scope | One pipeline per opened survey, owned by `MainWindow._pipelines: dict[survey_id, Pipeline]`. Retained for the session; lost on app quit. |
| Source node | Explicit non-removable "Source (raw amplitude)" row at top of the dock list. No enable checkbox, no params, no drag-reorder. Always tap-able. |
| Tap on disabled | Tap radio is greyed out on a disabled node. User must tap an enabled neighbour. If the currently-tapped node becomes disabled, tap auto-shifts to the nearest enabled upstream ancestor. |
| Tap on timeslice | Pipeline bypassed. Viewer paints raw timeslice. Dock stays interactive but tap clicks paint raw until the user switches axis. |
| Param editor placement | Selection-driven side panel inside the dock. Click a row → param widget for that node appears in a fixed area below the list. One node's params shown at a time. Mirrors the per-node editor M6 will dock alongside the visual canvas. |
| Cache key | `CacheKey.params_hash` from M4 is renamed to `chain_hash`. Same field, richer meaning. Source `chain_hash = blake2b(volume_version_blob)`. Node N `chain_hash = blake2b(plugin_id || version || params_hash || parent_chain_hash)`. Disabled node emits its parent's chain_hash unchanged (skip = identity). |
| Cache reuse | `SectionLRU` from M4 unchanged. Only `CacheKey` semantics shift. M4 in-memory cache entries from the same session do not survive the rename — acceptable, in-memory only. |
| Recompute trigger | Lazy: only the tap path recomputes on param change. Nodes downstream of the current tap stay dirty until tap moves to them. Tap switch then runs the suffix from the deepest cache hit. |
| Determinism propagation | Per-node. `deterministic=False` on node N means N and everything downstream skip cache reads/writes; nodes above N stay cacheable normally. |
| Duplicates | Same plugin can appear twice in a chain (different params, different node positions). Each `Node` has a UUID4 `node_id` that is GUI-only; cache keys ignore it. |
| Downstream input contract | Trace-local. A plugin in the chain sees its predecessor's output as `trace` (or `traces=batch` if vectorized). Plugin doesn't know it's chained. Context dict carries `sample_rate_ms`, `axis`, `index` — same shape as M4. |
| Execution model | Serial. Cold suffix runs node-by-node; each node waits on the previous node's `sectionReady` before starting. Tile-level parallelism within a node still applies via the M4 worker pool. Cross-node tile pipelining is M6/v1.1. |
| Coordination layer | New `eggseis.pipeline.PipelineExecutor(QObject)` between `MainWindow` and `JobOrchestrator`. Owns chain walking + cache lookup + serial execution. `JobOrchestrator` itself is barely touched: `request()` gains optional `input_section` and `chain_hash` overrides. |
| Cancellation | Single in-flight unit at the executor level. New `request_tap` cancels in-flight orch job (token) and drops the pending node queue. Late `sectionReady` events are dropped on job_id mismatch. |
| Pipeline persistence | None on disk in M5. M7 owns project save. |

Things deliberately not decided here:

- Branching, multi-input nodes, visual node-graph canvas — all M6.
- Cross-tile-cross-node parallelism — measure first; M6 at the earliest.
- Per-tile cache reuse across param changes — same reasoning as M4: trace-local plugins make this near-useless.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  MainWindow                                         │
│   ├── PipelineDock (Qt widget)                      │
│   │     ├── pipeline list (Source + nodes)          │
│   │     ├── selection-driven param panel            │
│   │     └── "+ Add" plugin picker                   │
│   ├── SectionViewer                                 │
│   ├── _pipelines: dict[survey_id, Pipeline]         │
│   └── _executor: PipelineExecutor                   │
└─────────────────┬───────────────────────────────────┘
                  │ request_tap(pipeline, volume, axis, index)
                  ▼
┌─────────────────────────────────────────────────────┐
│  PipelineExecutor (QObject) — eggseis.pipeline      │
│   ├── walks nodes 0..tap (honors enabled flags)     │
│   ├── computes chain_hash per node                  │
│   ├── checks SectionLRU at each node                │
│   ├── deepest cache hit found ⇒ skip earlier nodes  │
│   ├── for each remaining cold node:                 │
│   │     orch.request(spec, params, volume, axis,    │
│   │                  index, input_section,          │
│   │                  chain_hash)                    │
│   │     await sectionReady, store in cache,         │
│   │     feed into next node                         │
│   └── emits tapReady(job_id, ndarray)               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  JobOrchestrator (M4, mostly unchanged)             │
│   ├── debounce, threadpool, tile workers            │
│   ├── SectionLRU (chain_hash-keyed now)             │
│   └── one extension: request() takes optional       │
│       input_section override + chain_hash override  │
└─────────────────────────────────────────────────────┘
```

`Source` is not a `Node`. It is rendered in the dock with `node_id="source"` and treated by the executor as `tap_node_id == "source"` ⇒ short-circuit to raw `volume.read_*(index)`.

---

## Step 1: Package skeleton

```
src/eggseis/pipeline/
├── __init__.py        # re-exports Pipeline, Node, PipelineExecutor
├── model.py           # Node, Pipeline dataclasses + chain_hash math
├── executor.py        # PipelineExecutor(QObject) — coordinates orchestrator
└── dock.py            # PipelineDock(QDockWidget) — list + param panel + add button
```

`eggseis.pipeline` is a new package; nothing in M1–M4 imports it. `app.py` is the only existing module that grows substantially.

## Step 2: Pipeline model

```python
# src/eggseis/pipeline/model.py
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from pydantic import BaseModel

from eggseis.compute.cache import params_hash
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

    def append(self, node: Node) -> None: ...
    def remove(self, node_id: str) -> None: ...
    def move(self, node_id: str, new_index: int) -> None: ...
    def set_enabled(self, node_id: str, on: bool) -> None: ...
    def set_params(self, node_id: str, params: BaseModel) -> None: ...
    def set_tap(self, node_id: str) -> None: ...

    def nodes_up_to_tap(self) -> list[Node]:
        """Return enabled nodes from index 0 through the tap, inclusive.
        Disabled nodes are filtered out (skip = identity)."""
        ...

    def chain_hash_for(self, node_id: str, volume_version: tuple) -> str:
        """Compute chain_hash for the given node, walking from Source.
        Source hash = blake2b(volume_version_blob).
        Each enabled node folds in (plugin_id, plugin_version, params_hash).
        Disabled nodes pass parent hash through unchanged."""
        ...

    def deterministic_through(self, node_id: str) -> bool:
        """True if every enabled node up to and including node_id is deterministic."""
        ...
```

`chain_hash_for` is the heart of M5. Test it exhaustively (Step 8a).

## Step 3: Cache key rename

```python
# src/eggseis/compute/cache.py — rename only
@dataclass(frozen=True)
class CacheKey:
    plugin_id: str
    plugin_version: str
    chain_hash: str          # was params_hash
    axis: str
    index: int
    volume_version: tuple
```

Touch every M4 test that constructs a `CacheKey` literal: rename `params_hash=` → `chain_hash=`. M4 production code that builds keys (`JobOrchestrator._make_key`) is reviewed in Step 4.

## Step 4: Orchestrator extension

`JobOrchestrator.request` gains two optional kwargs:

```python
# src/eggseis/compute/orchestrator.py
def request(
    self,
    spec: PluginSpec,
    params: BaseModel,
    volume: SeismicVolume,
    axis: Axis | str,
    index: int,
    *,
    input_section: np.ndarray | None = None,   # skip read if provided
    chain_hash: str | None = None,             # override key for chained calls
) -> None:
```

When `input_section` is provided, the orchestrator skips its `_read` step and uses the supplied array as the section. When `chain_hash` is provided, `_make_key` uses it; otherwise it falls back to `params_hash(params.model_dump())` for backwards compatibility with single-attribute callers.

`_make_key` becomes:

```python
def _make_key(self, spec, params, volume, axis, index, *, chain_hash=None):
    return CacheKey(
        plugin_id=spec.id,
        plugin_version=spec.version,
        chain_hash=chain_hash or params_hash(params.model_dump()),
        axis=axis.value,
        index=index,
        volume_version=volume.version,
    )
```

Single-attribute callers (M3 GUI activate path used in M4) continue to work without code changes — they pass no `chain_hash` and get the M4 behaviour, which is just chain_hash = params_hash for a single-node chain. Equivalent value, different meaning.

## Step 5: Executor

```python
# src/eggseis/pipeline/executor.py
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from eggseis.axes import Axis
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.pipeline.model import Pipeline, SOURCE_ID


class PipelineExecutor(QObject):
    tapReady = Signal(int, object)              # job_id, ndarray (final tap output)
    intermediateReady = Signal(int, str, object)  # job_id, node_id, ndarray
    failed = Signal(int, str)                    # job_id, message

    def __init__(self, orchestrator: JobOrchestrator) -> None:
        super().__init__()
        self._orch = orchestrator
        self._orch.sectionReady.connect(self._on_section_ready)
        self._orch.failed.connect(self._on_orch_failed)
        self._plan: list = []        # remaining cold nodes
        self._working_input: np.ndarray | None = None
        self._volume = None
        self._axis = None
        self._index = None
        self._tap_id: str | None = None
        self._job_id: int | None = None  # current orch job id

    def request_tap(self, pipeline: Pipeline, volume: SeismicVolume, axis: Axis | str, index: int) -> None:
        # 1. Cancel any in-flight work + drop our queue.
        self.cancel_active()
        # 2. Resolve plan: nodes_up_to_tap (skips disabled).
        # 3. Walk plan from tap backward, looking up each chain_hash in cache.
        # 4. Deepest cache hit ⇒ start executing the suffix from that point.
        # 5. If no cold nodes (everything cached), emit tapReady directly.
        # 6. Otherwise issue the first cold node's request to orch and wait
        #    on sectionReady before issuing the next.
        ...

    def cancel_active(self) -> None:
        self._plan = []
        self._working_input = None
        self._orch.cancel_active()

    def _on_section_ready(self, job_id: int, arr: np.ndarray) -> None:
        # If job_id != self._job_id, drop (we cancelled or it's a stale event).
        # Otherwise: cache the result (orch already wrote it), advance plan.
        # If plan empty ⇒ emit tapReady. Else: issue next node's request.
        ...

    def _on_orch_failed(self, job_id: int, message: str) -> None:
        self._plan = []
        self.failed.emit(job_id, message)
```

The executor is a small state machine. Total: ~150 LOC including docstrings. Most of the logic is "find deepest cache hit then walk forward".

## Step 6: Dock widget

```python
# src/eggseis/pipeline/dock.py
class PipelineDock(QDockWidget):
    pipelineChanged = Signal()      # any structural / param change
    tapChanged = Signal(str)        # new tap_node_id

    def __init__(self, parent=None):
        ...
        self._list = QListWidget()  # one row per node + Source row at index 0
        self._param_host = QStackedWidget()  # holds magicgui widgets per node
        self._add_button = QPushButton("+ Add plugin")
        ...

    def bind(self, pipeline: Pipeline) -> None:
        """Render the given pipeline. Called by MainWindow on survey switch."""
        ...
```

Row widget per node:

```
┌────────────────────────────────────────────────┐
│ ☐ enable    [bandpass]                  ◯ tap │   <- drag handle on hover
└────────────────────────────────────────────────┘
```

Source row is fixed at the top, no enable checkbox or drag handle, but has a tap radio.

Param panel: when the user selects a node, `_param_host.setCurrentIndex(...)` switches to that node's magicgui widget. The widget's `changed` signal calls `pipeline.set_params(...)` then emits `pipelineChanged`.

Drag-reorder: `QListWidget.setDragDropMode(InternalMove)`; on `model().rowsMoved`, call `pipeline.move(...)` and emit `pipelineChanged`.

The "+ Add plugin" button opens a small picker (M3 plugin discovery output). Selecting a plugin instantiates `Node(spec, spec.param_model())` and appends.

## Step 7: GUI wiring

```python
# src/eggseis/app.py — additions
from eggseis.pipeline.model import Pipeline, SOURCE_ID
from eggseis.pipeline.dock import PipelineDock
from eggseis.pipeline.executor import PipelineExecutor


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        ...
        self._compute = JobOrchestrator()
        self._executor = PipelineExecutor(self._compute)
        self._executor.tapReady.connect(self._on_tap_ready)
        self._executor.failed.connect(
            lambda _id, msg: self.statusBar().showMessage(f"Compute failed: {msg}", 5000)
        )

        self._pipelines: dict[str, Pipeline] = {}
        self._pipeline_dock = PipelineDock()
        self._pipeline_dock.pipelineChanged.connect(self._request_tap)
        self._pipeline_dock.tapChanged.connect(lambda _: self._request_tap())
        self.addDockWidget(Qt.RightDockWidgetArea, self._pipeline_dock)

    def _on_survey_opened(self, survey_id: str, volume: SeismicVolume) -> None:
        if survey_id not in self._pipelines:
            self._pipelines[survey_id] = Pipeline()
        self._pipeline_dock.bind(self._pipelines[survey_id])
        self.section_viewer.set_volume(volume)
        self._request_tap()

    def _request_tap(self) -> None:
        if not self.section_viewer.has_volume:
            return
        pipeline = self._pipelines[self._active_survey_id]
        self._executor.request_tap(
            pipeline,
            self.section_viewer._volume,
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )

    def _on_tap_ready(self, job_id: int, arr: np.ndarray) -> None:
        self.section_viewer.set_overlay(arr, partial=False)
```

The M3 single-plugin "Apply attribute" menu path stays as a fallback for users who don't open the dock. Internally it can become a one-line "append + tap" against the survey's pipeline.

## Step 8: Tests

Use `pytest-qt`'s `qtbot.waitSignal` everywhere — never `time.sleep`.

### 8a — pipeline model

```python
# tests/test_pipeline_model.py
def test_chain_hash_stable_across_param_orderings(linear_spec):
    p1 = Pipeline()
    p1.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    p2 = Pipeline()
    p2.append(Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0)))
    vv = ("mdio", "/x", 1, 1)
    assert p1.chain_hash_for(p1.nodes[0].node_id, vv) == p2.chain_hash_for(p2.nodes[0].node_id, vv)


def test_chain_hash_changes_when_upstream_changes(linear_spec): ...
def test_disabled_node_passes_parent_hash_through(linear_spec): ...
def test_set_tap_to_disabled_shifts_to_upstream(linear_spec): ...
def test_deterministic_through_propagates(linear_spec, noise_spec): ...
def test_duplicate_plugin_distinct_node_ids_same_chain_hash(linear_spec): ...
```

### 8b — executor

```python
# tests/test_pipeline_executor.py
def test_empty_pipeline_taps_source_emits_raw(qtbot, sample_volume):
    orch = JobOrchestrator()
    exe = PipelineExecutor(orch)
    p = Pipeline()  # tap == SOURCE_ID by default
    with qtbot.waitSignal(exe.tapReady, timeout=2000) as blocker:
        exe.request_tap(p, sample_volume, "inline", sample_volume.geometry.inline_min)
    _jid, arr = blocker.args
    np.testing.assert_array_equal(arr, sample_volume.read_inline(sample_volume.geometry.inline_min))


def test_three_node_chain_executes_serially(qtbot, sample_volume, linear_spec):
    """linear_spec output = trace * scalar. Three nodes with scales 2, 3, 5
    ⇒ tap on rms-equivalent should equal raw * 30."""
    ...


def test_tap_switch_to_cached_node_paints_under_50ms(qtbot, sample_volume, linear_spec):
    """First request warms cache for all three nodes; second request taps node 1."""
    ...


def test_param_edit_invalidates_only_downstream(qtbot, sample_volume, linear_spec): ...
def test_cancel_on_new_request_drops_pending_queue(qtbot, sample_volume, slow_spec): ...
def test_disabled_middle_node_skips_in_chain(qtbot, sample_volume, linear_spec): ...
def test_non_deterministic_node_skips_cache_writes_downstream(qtbot, sample_volume, noise_spec, linear_spec): ...
def test_plugin_failure_halts_plan_and_emits_failed(qtbot, sample_volume, raising_spec): ...
def test_timeslice_axis_short_circuits_to_raw(qtbot, sample_volume, linear_spec): ...
def test_orphan_node_after_plugin_removed_blocks_downstream_tap(qtbot, sample_volume): ...
```

### 8c — dock

```python
# tests/test_pipeline_dock.py
def test_add_plugin_appends_node(qtbot, registry_with_envelope): ...
def test_remove_node(qtbot, registry_with_envelope): ...
def test_drag_reorder_moves_node(qtbot, registry_with_envelope): ...
def test_disable_greys_tap_radio(qtbot, registry_with_envelope): ...
def test_select_row_swaps_param_panel(qtbot, registry_with_envelope): ...
def test_param_change_emits_pipelineChanged_signal(qtbot, registry_with_envelope): ...
def test_source_row_non_removable_no_drag(qtbot): ...
```

### 8d — cache (rename)

Touch every existing M4 test that constructs `CacheKey(...)`: replace `params_hash="h"` with `chain_hash="h"`. No semantic change; sanity that the rename compiles + passes.

### 8e — GUI smoke

Extend `tests/test_gui_smoke.py`:

```python
def test_chain_three_attributes_tap_each(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume)

    # Add three plugins via the dock.
    from eggseis.builtins.ormsby_bandpass import ormsby_bandpass
    from eggseis.builtins.envelope import envelope
    from eggseis.builtins.rms_amplitude import rms_amplitude
    win._pipeline_dock.add_plugin(ormsby_bandpass._eggseis_spec)
    win._pipeline_dock.add_plugin(envelope._eggseis_spec)
    win._pipeline_dock.add_plugin(rms_amplitude._eggseis_spec)

    # Tap each in turn; assert overlay updates.
    pipeline = win._pipelines[win._active_survey_id]
    for node in pipeline.nodes:
        with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
            win._pipeline_dock.set_tap(node.node_id)
        assert win.section_viewer.has_overlay
```

### Test conventions for M5

- Always wait on executor signals; never `time.sleep`.
- Reuse `slow_spec`, `noise_spec` fixtures from M4. Add `linear_spec` (output = trace * scalar) for compositional chain assertions, and `raising_spec` (raises in `func`) for failure path.
- Build a `make_pipeline(specs, params=None)` factory in `tests/conftest.py`.
- Reuse the `clear_registry()` autouse pattern from M3 for any test that registers fixture plugins.

## Step 9: CLI / docs

- No new CLI commands. `eggseis info` and `eggseis dump-inline` continue to use synchronous `run_on_section`.
- Add a section to `docs/development.md` titled "How pipelines work in the GUI" — one paragraph each on: per-survey scope, chain_hash semantics, lazy recompute, tap mechanics.
- Update `docs/plugin-authoring.md`: a short note that `deterministic=False` plugins poison their chain downstream as well as themselves; recommend `deterministic=True` whenever feasible.
- README status: add line under M4 entry — "M5: pipeline chain — list-style dock, tap-anywhere, lazy recompute."

## Step 10: Status surface

- Status bar shows `"Computing {node N of M}: {plugin_name}…"` while the executor is mid-plan; clears on `tapReady`.
- `Help → Compute Errors` (from M4) gains an extra column for `node_id` + plugin name in chained errors.
- Dock row gets a red error icon when a node's last execution failed; click clears it.
- No cache-hit-rate UI. Same stance as M4.

---

## Execution order

1. `eggseis.pipeline` package skeleton + `Node`/`Pipeline` data model + `chain_hash_for` math. Tests for chain_hash stability and disabled-node identity (Step 8a). No Qt yet.
2. Rename `CacheKey.params_hash → chain_hash`. Touch every test. M4 suite stays green.
3. Extend `JobOrchestrator.request` with `input_section` and `chain_hash` kwargs. Add a unit test that single-attribute (no chain_hash) callers still produce identical keys to M4.
4. `PipelineExecutor` — start with the all-cached fast path (synchronous tapReady from cache). Test it.
5. Add cold-node serial execution path. Test 3-node chain with `linear_spec` (Step 8b).
6. Add cancellation + slow_spec tests.
7. Add disabled-node + determinism tests.
8. Build `PipelineDock` headlessly; tests under `QT_QPA_PLATFORM=offscreen` (Step 8c).
9. Wire into `MainWindow`; extend `test_gui_smoke.py` (Step 8e).
10. Status surface + error log integration.
11. `./scripts/test.sh ci` green on all three platforms.

Two-and-a-half weekends if disciplined. Likely time-sink: the dock widget's drag-reorder + selection-driven param panel, where Qt edge cases bite hardest. Build that with a tight feedback loop (`./scripts/test.sh demo`) rather than tests-first.

---

## Risks

- **Cache key drift across milestones.** Renaming `params_hash` to `chain_hash` is a one-shot break. After M5 ships, do not rename the field again — anyone persisting cache keys to disk in M5+ will rely on this name. (M4's drift warning still applies if anyone swaps the hash function.)
- **Serial execution latency on long cold chains.** A 5-node cold chain on a 1000×1500 section serializes 5 orch jobs, each ~200–500 ms. Total ~1–2.5 s for a fully cold tap. Mitigation: most realistic edits change one node, so the chain is rarely fully cold. If users complain, M6's tile-cross-node pipelining is the answer.
- **Stale orch event after cancel.** Documented in M4. Executor's job_id mismatch check is the second line of defence; first line is `orch.cancel_active()` setting the cancellation token before the new request lands. Tested in `test_cancel_on_new_request_drops_pending_queue`.
- **Dock + magicgui parameter widget lifecycle.** When a node is removed, its magicgui widget must be deleted (or it leaks Qt objects). Test by adding/removing 100 nodes in a row and asserting `gc.collect()` reclaims them — but only if `pytest-qt` makes that easy; otherwise lean on manual smoke during demo.
- **Plugin reload in mid-session.** The orphan-node case in Step 8b. Surface clearly; do not crash. The tap-shifting heuristic ("auto-shift to nearest enabled upstream ancestor") needs to handle the case where the orphan IS the upstream ancestor — fall back further, or fall through to Source.
- **Same-survey-different-window in some hypothetical multi-window future.** Out of scope; document that `_pipelines` is keyed on the survey id treated as canonical.
- **Dock as `QDockWidget` vs as a panel inside the central widget.** Dock-widget approach lets users tear it off / close it. Closing it must not delete the pipeline — pipeline lives on `MainWindow`, dock is a view. Test by closing + reopening the dock and asserting the pipeline survives.

---

## Out of scope for M5

- Branching, multi-input nodes, ports — M6.
- Visual node-graph canvas — M6.
- Project-file persistence (write `project.yaml`) — M7.
- Volume-wide compute — M6+.
- Cross-tile-cross-node parallelism — M6 / v1.1.
- Disk-backed cache — v1.1.

---

## When M5 is done

A clean exit looks like:

- `bandpass → envelope → rms_amplitude` chain on the F3 fragment. Tap each; section repaints to that node's output. Tap-warm switch is sub-50 ms locally.
- Edit `bandpass.f2` slider: nodes 2 and 3 recompute live; node 1's previous output is still in cache and revisits to the prior `f2` are instant.
- Disable `envelope`: chain becomes `bandpass → rms`; tap radio on `envelope` is greyed; downstream output is consistent with running `rms_amplitude(bandpass(raw))` directly.
- Headless tests cover model, executor, dock, cache rename, and a 3-node end-to-end smoke.
- README and `docs/development.md` updated. CHANGELOG entry under `[v0.1.0a5]`.
- Tag `v0.1.0a5` after the M5 PR merges.
- Take a beat. Then start M6 — "The graph branches."
