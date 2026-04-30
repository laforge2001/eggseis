# M6 — "The graph branches"

**Milestone 6 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M5-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Replace the linear pipeline with a real DAG. Multi-input plugins (e.g. `subtract(a, b)`) become first-class. Every output port of every enabled node is tappable. A visual node-graph canvas lets the user pan/zoom, drag boxes, wire ports, and inspect any port's output by clicking it.

This is the milestone where eggseis stops being a section viewer with effects stacked on it and starts being a node-based attribute composition platform. The cache-key chain shipped in M5 generalises here from a single linear running hash into a per-output-port hash that folds in every upstream port's hash. The list-dock UI shipped in M5 is replaced by a canvas; the per-node param editor M5 docked under the list moves to a side panel beside the canvas.

## Exit criteria

You're done with M6 when this is true:

- Build a non-trivial graph on the F3 fragment: `bandpass → envelope` and `bandpass → instantaneous_phase`, both feeding a `crossplot_pair(x, y)` node (single-output for now, output is the `x` array; the second output port arrives in M9). Tap each port; outputs verified against direct M5 chain compute on the equivalent linearisation.
- Multi-input node `subtract(a, b)` ships as a built-in. Wire `envelope` into `a`, `bandpass` into `b`; tap `subtract.out`; result equals `envelope(raw) - bandpass(raw)` element-wise.
- Visual canvas: drag a node, wire two ports, multi-select with rubber-band, delete selection, undo/redo last 20 ops. All keyboard-accessible (Delete key, Ctrl+Z / Ctrl+Y).
- Tap-anywhere works on every output port. Tap radio replaced by "click an output port to tap"; the tapped port glows. Tapping an input port shows its incoming edge's source-port output (delegated tap).
- Cycle attempt fails loudly with a clear error message at edge-creation time. The wire snaps back; status bar shows `"Cycle: would create A → B → A"`.
- Save/restore the graph round-trips in memory: build a graph, serialise to dict, reconstruct, verify topology + params + tap identical. Project-file persistence stays M7's job.
- Tap switch on a cache-warm port paints in **<50 ms** (inherits M4 cache hit budget).
- Per-output-port cache key: `blake2b(plugin_id || version || params_hash || sorted(input_port_keys))`. Source ports keyed off `volume_version` exactly as M5's source hash. Disabled single-input nodes pass parent through (identity); disabled multi-input nodes are not allowed (UI greys "disable" on multi-input rows).
- `@graph_node(inputs=("a","b"), output="result")` decorator works and `@trace_attribute` continues to function unchanged as the single-input shorthand. Both populate the same registry.
- Headless tests cover: graph topology (cycles rejected, topo order correct), per-port chain math, branch invalidation precise (editing one branch leaves the other's caches intact), multi-input execution, undo/redo, serialisation round-trip.
- `eggseis info` and `eggseis dump-inline` still work and ignore the graph layer (CLI keeps its synchronous single-attribute path).
- M5 user-facing pipelines are migrated transparently on session reload: the linear `Pipeline` class is gone; `_pipelines: dict[survey_id, Graph]` replaces it. No back-compat shim needed (in-memory only, lost on app quit).

---

## Locked design decisions for M6

| Area | Decision |
|---|---|
| Topology | Directed acyclic graph. Nodes have N input ports (named) and 1 output port in v1.0. Multiple outputs per node deferred to v1.1; M9's `crossplot_pair` lives in single-output land for M6 by emitting only `x`. |
| Source representation | The graph has an implicit `Source` node (id = `"source"`) with three output ports: `inline`, `xline`, `timeslice`. The active section axis selects which port feeds downstream. No user-creatable replacement; cannot be deleted. |
| Edge model | An edge connects `(src_node_id, src_port="out")` → `(dst_node_id, dst_port_name)`. Each input port accepts at most one edge; rewiring replaces. Output ports fan out arbitrarily. |
| Port type | `np.ndarray` only in v1.0. Type-checking is structural (shape matched at execution; mismatched shapes raise at the executing node). No declared dtype/shape constraints in the wire layer. |
| Plugin decorator | `@graph_node(name?, version="0.1.0", inputs=("a", "b", ...), deterministic=True)` is the general form. `@trace_attribute` becomes a thin wrapper that emits a `@graph_node(inputs=("trace",))` spec. Both register into the same `_REGISTRY`; both expose `.spec.inputs` (a tuple of port names) and `.spec.output` (always `"out"` in v1.0). |
| Tap | `tap_port: tuple[node_id, port_name]`. Source default = `(SOURCE_ID, "inline")`, axis-driven. Click an input port = follows the edge to the source port (delegated tap). Tap ID always names an output port internally. |
| Disable semantics | Single-input nodes (i.e. plugins decorated with `@trace_attribute` or `@graph_node(inputs=("x",))`): disable = identity, child gets parent's port hash. Multi-input nodes: disable is disallowed (greyed in UI). Removal is the multi-input "delete me" path. |
| Cache key | `port_hash(node_id, port_name)` = `blake2b(plugin_id || version || params_hash || sorted_input_port_hashes)`. Source ports = `blake2b(volume_version || axis)`. `CacheKey.chain_hash` field name retained from M5; semantics widen from "linear chain" to "this port's full upstream cone". |
| Cache reuse | `SectionLRU` from M4 unchanged. Existing M5 entries stay valid: a single-input chain produces the same hash chain as before since `sorted_input_port_hashes == [parent_hash]` and the fold function is identical. |
| Determinism propagation | Same as M5: per-node. `deterministic=False` on node N poisons N and every node in its downstream cone (any port whose computation reads from N's output skips cache reads/writes). |
| Execution model | Serial topological order. For a tap, executor computes the upstream cone of the tapped port via reverse-BFS, finds the deepest cache hits per branch, then runs the cold suffix in topo order. Within each node, M4 tile-parallelism unchanged. Cross-node tile pipelining: still deferred. |
| Multi-input feeding | Each input port for a cold node must have its source-port array in hand before the node runs. Executor blocks topo advancement until all of a node's inputs are resolved (cache hit or completed orchestrator job). |
| Coordination layer | M5's `PipelineExecutor` is renamed and generalised to `GraphExecutor`. Public API converges on `request_tap(graph, volume, axis, index)`. The list-dock-specific entry points are dropped. |
| Cancellation | Single in-flight tap at the executor level. New `request_tap` cancels every pending node job and disconnects all per-step orchestrator slots. Late `sectionReady` events drop on `job_id` mismatch (same defence as M5). |
| Visual canvas | **Library: `qtpynodeeditor` 0.3.3** (3-clause BSD; pure Python port of Pinaev's `nodeeditor`). Spike cleared on macOS / PySide6 6.11 / Python 3.12 — see Step 0 for details and caveats. Built-in cycle detection (with a known dangling-state quirk we route around). Canvas widget lives in `eggseis.graph.canvas`; if Linux or Windows CI later fails to import the lib, fall back to the M5 list-dock with port columns on the affected platform. |
| Param editor | Selection-driven side panel docked beside the canvas. Same magicgui factory used in M5. One node's params shown at a time. Source node has no params. |
| Undo/redo | Operation stack inside `Graph` (typed ops: `AddNode`, `RemoveNode`, `Connect`, `Disconnect`, `SetParams`, `SetTap`). 20-deep ring buffer. Canvas wires Ctrl+Z / Ctrl+Y to `graph.undo()` / `graph.redo()`. |
| Serialisation | `Graph.to_dict()` / `Graph.from_dict(d, registry)`. Round-trip is the M6 acceptance test; persistence to `project.yaml` is M7's call. |
| Per-survey scope | One graph per opened survey. `MainWindow._graphs: dict[survey_id, Graph]`. Lost on app quit. Same shape as M5's `_pipelines`. |
| CLI / library | Untouched. `eggseis info`, `eggseis dump-inline`, `run_on_section` keep their synchronous single-attribute behaviour. The graph is a GUI concept. |

Things deliberately not decided here:

- Multiple output ports per node — v1.1; `crossplot_pair` ships in M9 as the first real consumer.
- Cross-node tile-pipelining — measure first; not before v1.1.
- DAG persistence to disk — M7.
- Subgraphs / encapsulation / parameterised macros — out of scope for v1.0.
- Read-only "computed" nodes (e.g. histogram) that don't emit a viewable section — out of scope; everything is a section-shaped ndarray in v1.0.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  MainWindow                                         │
│   ├── GraphCanvas (Qt widget)                       │
│   │     ├── qtpynodeeditor FlowScene + FlowView     │
│   │     ├── output-port-click → set_tap             │
│   │     └── + Add plugin (palette / right-click)    │
│   ├── ParamDock (selection-driven, magicgui host)   │
│   ├── SectionViewer                                 │
│   ├── _graphs: dict[survey_id, Graph]               │
│   └── _executor: GraphExecutor                      │
└─────────────────┬───────────────────────────────────┘
                  │ request_tap(graph, volume, axis, index)
                  ▼
┌─────────────────────────────────────────────────────┐
│  GraphExecutor (QObject) — eggseis.graph            │
│   ├── reverse-BFS upstream cone of tap_port         │
│   ├── computes port_hash per port                   │
│   ├── checks SectionLRU at each output port         │
│   ├── deepest cache hits define the cold frontier   │
│   ├── topo-walks the cold subgraph:                 │
│   │     for each cold node with all inputs ready,   │
│   │     orch.request(spec, params, volume, axis,    │
│   │                  index, input_sections,         │
│   │                  chain_hash=port_hash)          │
│   │     await sectionReady, store, advance          │
│   └── emits tapReady(job_id, ndarray)               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  JobOrchestrator (M4, mostly unchanged)             │
│   ├── debounce, threadpool, tile workers            │
│   ├── SectionLRU (port_hash via chain_hash field)   │
│   └── one extension: request() takes optional       │
│       input_sections=dict[port_name, ndarray]       │
└─────────────────────────────────────────────────────┘
```

`Source` is a real `Node` in M6 (it was a sentinel in M5). It has fixed output ports `inline`, `xline`, `timeslice`; the executor satisfies them by reading from the volume directly when the cone touches them. It cannot be deleted, has no params, and its enable state is fixed True.

---

## Step 0: Canvas library spike — **DONE, qtpynodeeditor cleared**

Per ROADMAP risk note. Time-boxed; ran ahead of plan execution. Two libs evaluated: `NodeGraphQt 0.6.44` (original target) and `qtpynodeeditor 0.3.3` (alternative). **Switched to `qtpynodeeditor`** — better maintenance, cleaner Python 3.12 story, built-in cycle detection.

**Verdict: proceed with `qtpynodeeditor 0.3.3`.** macOS / PySide6 6.11 / Python 3.12 spike (`examples/canvas_spike.py`) confirmed:

- Subclassing `NodeDataModel` + attaching plugin metadata (`plugin_id`, `plugin_version`) round-trips cleanly.
- Multi-input nodes via `num_ports = {input: N, output: M}` — first-class.
- Programmatic wire via `scene.create_connection(out_port, in_port)`; programmatic delete via `scene.delete_connection(conn)`.
- Port + connection introspection: `port.connections`, `conn.get_node(PortType.output)`, `conn.get_port_index(...)`.
- Scene signals fire as expected: `node_created`, `node_deleted`, `connection_created`, `connection_deleted` — direct hooks for syncing `Graph` model to canvas.
- Headless under `QT_QPA_PLATFORM=offscreen` works as long as a `FlowView` is attached (graphics objects only exist with a view).
- **Built-in cycle detection.** `ConnectionCycleFailure` raised when wiring `s.out → a.in` while `a → s` already exists. Better than `NodeGraphQt`, which silently allowed cycles.
- Pure Python; imports clean on Python 3.12; no `distutils` shim needed.
- `qtpy` compat layer means we are not locked to one Qt binding.
- Bonus: typed ports (we register a single `SectionData.data_type`, the lib enforces wire compatibility).

**Why we did NOT pick `NodeGraphQt`:**

- Last release May 2023 vs `qtpynodeeditor` Dec 2024.
- Imports `distutils.version.LooseVersion`, removed in Python 3.12 — works only with `setuptools` shim.
- No built-in cycle detection; we'd have to roll our own and disconnect on reject after-the-fact.

**Caveats taken into the plan:**

- **Cycle detection has a known dangling-state bug.** When `ConnectionCycleFailure` is raised, the lib leaves the failed wire in the port's `.connections` list. Mitigation: never rely on the lib's detection — pre-validate every wire via `Graph.has_cycle_if_added` BEFORE calling `scene.create_connection`. The lib's exception is a defence-in-depth backstop, not the primary check.
- **`set_in_data` / `data_updated` propagation must be ignored.** The lib auto-propagates data through wires by calling `set_in_data` on downstream nodes, which then re-emits `data_updated`, which calls `move_connections` on graphics objects. In a view-less scene this NPEs; in a view-attached scene it does pointless work. We treat the lib's data flow as decorative and own all compute inside `GraphExecutor`. Our `_PluginNode.set_in_data` is a no-op (does not emit `data_updated`); our `_PluginNode.out_data` returns a `SectionData()` sentinel only.
- **Per-port `data_type` dict.** When a node has multi-input ports, declare `data_type = {input: {0: dt, 1: dt}, output: {0: dt}}` explicitly per-port, not as a scalar. The lib's `_verify` expands scalar → dict at class-definition time; subclassing with different `num_ports` after the dict is built leaves orphan ports. Document the helper `_section_dict(n_in, n_out)` in `_PluginNode`.
- **Headless tests need a `FlowView`.** Tests must instantiate `FlowView(scene)` even though they never `.show()`, otherwise connection deletion crashes on `move_connections`.
- **Linux / Windows CI smoke import.** Not yet exercised (spike macOS-only). Fold into Step 1's first CI run. If either platform fails to import the lib under PySide6 6.11+, fall back to the list-dock-with-port-columns variant. The fallback path described in ROADMAP remains live until Linux + Windows CI is green.

Spike artefact (`examples/canvas_spike.py`) stays in the tree as the simplest reproducer for the data-propagation NPE and cycle-leftover bug; both are worth reporting upstream after M6 ships.

## Step 1: Package skeleton

```
src/eggseis/graph/
├── __init__.py        # re-exports Graph, Node, Edge, GraphExecutor, SOURCE_ID
├── model.py           # Graph, Node, Edge, port_hash math, undo stack, serialisation
├── executor.py        # GraphExecutor(QObject) — topo walk, multi-input, cache
├── canvas.py          # GraphCanvas(QWidget) — qtpynodeeditor-backed scene
└── param_dock.py      # ParamDock(QDockWidget) — selection-driven param editor
```

`eggseis.graph` is a new package. `eggseis.pipeline` is removed in this milestone (its M5 callers in `app.py` switch over). The `Pipeline` / `PipelineExecutor` symbols are deleted, not deprecated — graph supersedes pipeline cleanly because nothing outside `app.py` and the dock/test layer imported pipeline.

## Step 2: Graph data model

```python
# src/eggseis/graph/model.py
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from eggseis.compute.cache import params_hash
from eggseis.plugin import PluginSpec

SOURCE_ID = "source"
SOURCE_PORTS = ("inline", "xline", "timeslice")


@dataclass(frozen=True)
class Edge:
    src_node_id: str
    src_port: str            # always "out" except SOURCE_ID
    dst_node_id: str
    dst_port: str            # one of dst_node.spec.inputs


@dataclass
class Node:
    spec: PluginSpec
    params: BaseModel
    enabled: bool = True
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    pos: tuple[float, float] = (0.0, 0.0)   # canvas position; round-tripped in to_dict


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    tap_port: tuple[str, str] = (SOURCE_ID, "inline")
    _undo: list = field(default_factory=list)
    _redo: list = field(default_factory=list)

    # Topology
    def add_node(self, node: Node) -> None: ...
    def remove_node(self, node_id: str) -> None: ...
    def connect(self, edge: Edge) -> None:
        """Reject cycles. Replace any existing edge into (dst_node_id, dst_port)."""
        ...
    def disconnect(self, edge: Edge) -> None: ...
    def set_params(self, node_id: str, params: BaseModel) -> None: ...
    def set_enabled(self, node_id: str, on: bool) -> None:
        """Disabling multi-input nodes raises ValueError."""
        ...
    def set_tap(self, node_id: str, port: str = "out") -> None: ...

    # Queries
    def upstream_cone(self, node_id: str, port: str) -> list[str]:
        """Topologically-ordered list of node ids whose output reaches (node_id, port).
        Filters out disabled single-input nodes (their input edge is short-circuited
        to grandparent at hash and execution time). Includes SOURCE_ID iff reached."""
        ...
    def incoming_edges(self, node_id: str) -> dict[str, Edge]:
        """{dst_port: edge} for the given node."""
        ...
    def has_cycle_if_added(self, edge: Edge) -> bool: ...

    # Hashing
    def port_hash(self, node_id: str, port: str, volume_version: tuple, axis: str) -> str:
        """blake2b digest of upstream cone ending at (node_id, port).

        - SOURCE_ID + port in {inline, xline, timeslice}: hash(volume_version || port).
          (We fold axis-port into the source hash so different axes don't collide.)
        - Other nodes:
            inputs = sorted(port_hash(edge.src_node_id, edge.src_port, ...) for edge in incoming)
            digest(plugin_id || version || params_hash(node.params) || inputs)
        - Disabled single-input node: pass parent's port_hash through unchanged.
        """
        ...

    def deterministic_through(self, node_id: str, port: str) -> bool:
        """True iff every enabled node in the upstream cone of (node_id, port) is deterministic."""
        ...

    # Undo/redo
    def undo(self) -> None: ...
    def redo(self) -> None: ...

    # Serialisation
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: dict[str, Any], registry) -> "Graph":
        """`registry` is the result of eggseis.plugin.registered() at load time;
        unknown plugin_ids raise OrphanPluginError. M7 will surface this in the UI."""
        ...
```

`port_hash` is the heart of M6. Test it exhaustively (Step 9a). Note the canonical-JSON encoding of the `inputs` list — sorted before hashing so port-order in incoming-edge iteration doesn't matter.

The undo stack is a simple typed-op log. Each public mutator pushes its inverse op into `_undo`; a successful `undo()` pops one and pushes onto `_redo`. Mutators called from inside `undo()`/`redo()` must not push to `_undo` (private flag, set during replay).

## Step 3: Plugin decorator generalisation

```python
# src/eggseis/plugin.py — extensions

@dataclass(frozen=True)
class PluginSpec:
    id: str
    name: str
    func: Callable[..., np.ndarray]
    param_model: type[BaseModel]
    params_decl: dict[str, Param]
    vectorized: bool
    deterministic: bool
    version: str
    source_path: str | None
    accepts_context: bool
    inputs: tuple[str, ...]      # NEW. ("trace",) for trace_attribute.
    output: str = "out"          # NEW. Reserved for v1.1 multi-output.


def graph_node(
    *,
    name: str | None = None,
    version: str = "0.1.0",
    inputs: tuple[str, ...] = ("input",),
    deterministic: bool = True,
) -> Callable: ...
```

`graph_node` mirrors `trace_attribute`'s decorator body but reserves `inputs` (tuple of port names) instead of the magic `trace` / `traces` / `context` names. Each input port name corresponds to a positional or keyword argument the plugin function declares; non-input args with `Param(...)` defaults still become pydantic fields. `context` continues to work as the optional sidecar dict.

`trace_attribute` becomes:

```python
def trace_attribute(*, name=None, version="0.1.0", vectorized=False, deterministic=True):
    """Single-input shorthand. Equivalent to graph_node(inputs=("trace" or "traces",))
    with vectorisation handling unchanged."""
    ...
```

Internally, `trace_attribute` instantiates the same `PluginSpec` with `inputs=("trace",)` for scalar mode or `inputs=("traces",)` for vectorised. The runner (`plugin_runner.py`) bridges port-name → call-arg mapping for both paths.

Built-in `subtract(a, b)` ships under `eggseis/builtins/subtract.py`:

```python
@graph_node(name="Subtract", inputs=("a", "b"))
def subtract(a, b):
    return a - b
```

No params; pure shape-based subtraction. Document the requirement that both inputs share a shape.

## Step 4: Cache + orchestrator extensions

`CacheKey.chain_hash` field name is unchanged from M5. Semantics widen: it still names "the digest identifying this output's full upstream history" — M5 was a chain, M6 is a cone, but the canonical-JSON-of-fold-tree is shape-equivalent for linear chains, so existing M5 tests keep their hash literals only if those tests build single-input graphs. (They do; the rename in Step 2 of M5 already paid that cost.)

`JobOrchestrator.request` gains:

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
    input_section: np.ndarray | None = None,        # M5; deprecated alias for input_sections
    input_sections: dict[str, np.ndarray] | None = None,  # NEW. Per-port input arrays.
    chain_hash: str | None = None,
    skip_cache_write: bool = False,
) -> None: ...
```

`input_section` is kept as a thin alias one milestone for in-tree callers; M5's executor went away anyway, so the only caller is single-attribute apply. Internally we always normalise to `input_sections`. The plugin runner reads `spec.inputs` and pulls the matching array per port name.

Single-input callers (M3 GUI activate path) still work without changes. Their absent `input_sections` falls back to a synthesised `{spec.inputs[0]: read_axis(index)}`.

## Step 5: GraphExecutor

```python
# src/eggseis/graph/executor.py
class GraphExecutor(QObject):
    tapReady = Signal(int, object)                 # job_id, ndarray
    intermediateReady = Signal(int, str, str, object)  # job_id, node_id, port, ndarray
    failed = Signal(int, str)                       # job_id, message
    progress = Signal(int, int, str)                # nodes_done, total_cold, current_plugin

    def __init__(self, orchestrator: JobOrchestrator) -> None: ...

    def request_tap(self, graph: Graph, volume: SeismicVolume,
                    axis: Axis | str, index: int) -> None:
        """
        1. Cancel any in-flight plan + drop pending node queue.
        2. Resolve the tap port. If SOURCE_ID, paint raw and return.
        3. Compute upstream cone (topo order).
        4. For each node in reverse-topo, compute port_hash and check cache.
           Stop at the deepest cache-hit frontier (per-branch).
        5. Cold subgraph = cone minus already-cached frontier.
        6. Topologically execute cold subgraph: a node fires when every input's
           array is in hand (cache hit OR completed orch job for that input).
        7. Emit tapReady when the tapped output port is in hand.
        """
        ...

    def cancel_active(self) -> None: ...
```

Internal state during a plan:

- `_resolved: dict[(node_id, port), np.ndarray]` — outputs available.
- `_pending: dict[node_id, set[port]]` — input ports still waiting.
- `_runnable: deque[node_id]` — nodes whose `_pending` is empty.

Loop: pop runnable, issue `orch.request(spec, params, volume, axis, index, input_sections=…)`, `await sectionReady`, drop result into `_resolved`, walk dst-edges to update `_pending` of descendants, push newly-runnable ones into the deque. Continue until tap port is `_resolved`.

Total: ~250 LOC including topo BFS + cancel. The state-machine shape is M5's executor inflated by one dimension; structure stays simple.

## Step 6: Canvas widget

Conditional on Step 0's spike result.

**qtpynodeeditor path (default):**

```python
# src/eggseis/graph/canvas.py
class GraphCanvas(QWidget):
    nodeAdded = Signal(str)                  # node_id
    nodeRemoved = Signal(str)
    edgeChanged = Signal()                   # any wire add/remove (model already mutated)
    tapPortClicked = Signal(str, str)        # node_id, port
    selectionChanged = Signal(str)           # node_id selected (or "")

    def __init__(self, parent=None) -> None: ...
    def bind(self, graph: Graph) -> None: ...
    def add_plugin(self, spec: PluginSpec, pos: tuple[float, float] | None = None) -> str: ...
```

The widget composes a `qtpynodeeditor.FlowScene` + `FlowView` and wires its signals (`node_created`, `node_deleted`, `connection_created`, `connection_deleted`, `node_double_clicked`, `selection_changed`) into our model.

Per-plugin canvas class is generated dynamically from the `PluginSpec` registry: a `_make_node_class(spec)` factory returns a `NodeDataModel` subclass with `num_ports`, `port_caption`, and per-port `data_type` populated from `spec.inputs` / `spec.output`. Class is cached and registered with the scene's `DataModelRegistry`. The `Source` node is a singleton `_SourceNode(NodeDataModel)` with no inputs and three outputs (`inline`, `xline`, `timeslice`).

The lib's data-propagation is suppressed in our nodes — `set_in_data` is a no-op and we never emit `data_updated`. All compute lives in `GraphExecutor`.

Tap interaction: right-click on an output port shows a context menu "Tap here"; double-clicking an output port toggles it as the tap. Decide between Shift-click vs context-menu in demo; document choice in PR. Tapped port rendered with heavier outline + glow via `port_caption` decoration or `_render_decoration` hook.

Cycle handling: hook `connection_created` signal. On every fire, look up the new edge in our `Graph` and call `Graph.has_cycle_if_added`. If cycle, call `scene.delete_connection(conn)` and `statusBar.showMessage("Cycle: would create A → … → A", 5000)`. The lib's own `ConnectionCycleFailure` exception is a backstop — wrap `scene.create_connection` to also catch it and translate to status message; remember to clean up the dangling-connection-on-failure bug by walking `port.connections` and removing the failed wire reference.

Undo/redo: Ctrl+Z / Ctrl+Y on the canvas widget call `graph.undo()` / `graph.redo()`; after mutation, `bind(graph)` re-renders the scene. (The lib has no undo stack of its own — single source of truth is our typed-op log.)

**Fallback path (no canvas):** extend M5's `PipelineDock` into a multi-row table where each row gets one cell per declared input port; the cell is a combobox of "node X output port" selections. Source row stays. Tap radios extend to one-per-output (only one column needed since v1.0 outputs are single). Drop drag-reorder (DAG order is implicit). All other surfaces unchanged. Document this fallback in README under M6 status.

## Step 7: Param dock

```python
# src/eggseis/graph/param_dock.py
class ParamDock(QDockWidget):
    paramsChanged = Signal(str, object)  # node_id, params model

    def bind(self, graph: Graph) -> None: ...
    def show_node(self, node_id: str | None) -> None:
        """Switch the displayed widget. None or SOURCE_ID -> empty pane."""
        ...
```

Reuses the magicgui-from-pydantic factory established in M3. Factory caches one widget per node id keyed by `(node_id, params_model_class)`; rebuilds when the model changes (rare — only on plugin reload).

When the canvas's `selectionChanged(node_id)` fires, the dock calls `show_node(node_id)`. Param-widget changes flow `dock.paramsChanged → MainWindow → graph.set_params → executor.request_tap`.

## Step 8: GUI wiring

```python
# src/eggseis/app.py — additions
from eggseis.graph.model import Graph, SOURCE_ID
from eggseis.graph.canvas import GraphCanvas
from eggseis.graph.executor import GraphExecutor
from eggseis.graph.param_dock import ParamDock

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        ...
        self._compute = JobOrchestrator()
        self._executor = GraphExecutor(self._compute)
        self._executor.tapReady.connect(self._on_tap_ready)
        self._executor.failed.connect(
            lambda _id, msg: self.statusBar().showMessage(f"Compute failed: {msg}", 5000)
        )

        self._graphs: dict[str, Graph] = {}
        self._canvas = GraphCanvas()
        self._canvas.tapPortClicked.connect(self._on_tap_changed)
        self._canvas.edgeChanged.connect(self._request_tap)

        self._param_dock = ParamDock()
        self._param_dock.paramsChanged.connect(self._on_params_changed)
        self._canvas.selectionChanged.connect(self._param_dock.show_node)

        self.setCentralWidget(self._canvas)  # canvas is the new central work surface
        self.addDockWidget(Qt.RightDockWidgetArea, self._param_dock)
        # SectionViewer becomes a dock — it's no longer the central widget. M7 will
        # let users open more than one. For M6, ship one bottom-docked viewer.
        self.addDockWidget(Qt.BottomDockWidgetArea, self.section_viewer_dock)

    def _on_survey_opened(self, survey_id: str, volume: SeismicVolume) -> None:
        if survey_id not in self._graphs:
            self._graphs[survey_id] = Graph()
        self._canvas.bind(self._graphs[survey_id])
        self._param_dock.bind(self._graphs[survey_id])
        self.section_viewer.set_volume(volume)
        self._request_tap()

    def _request_tap(self) -> None:
        if not self.section_viewer.has_volume:
            return
        graph = self._graphs[self._active_survey_id]
        self._executor.request_tap(
            graph,
            self.section_viewer._volume,
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )

    def _on_tap_changed(self, node_id: str, port: str) -> None:
        graph = self._graphs[self._active_survey_id]
        graph.set_tap(node_id, port)
        self._request_tap()

    def _on_tap_ready(self, job_id: int, arr: np.ndarray) -> None:
        self.section_viewer.set_overlay(arr, partial=False)
```

The M5 "Apply attribute" menu becomes a graph operation: it appends a node connected to the Source `inline` port (or the active axis) and sets the tap to the new node's output. The implementation is one helper on `Graph`: `Graph.append_to_active_axis(spec, axis)`.

Layout shift: SectionViewer was the central widget through M5; in M6 the canvas is central and SectionViewer moves to a dock at the bottom. Document the relayout in `docs/development.md`.

## Step 9: Tests

`pytest-qt` + `qtbot.waitSignal` + `qtbot.waitUntil` everywhere. No `time.sleep`.

### 9a — graph model

```python
# tests/test_graph_model.py
def test_source_node_singleton(): ...
def test_add_node_and_connect_simple(linear_spec): ...
def test_connect_replaces_existing_inbound_edge(linear_spec): ...
def test_cycle_rejected_on_connect(linear_spec):
    """A → B → A must raise; graph state must be unchanged after the failed call."""
    ...
def test_port_hash_stable_across_param_orderings(linear_spec): ...
def test_port_hash_changes_when_upstream_changes(linear_spec): ...
def test_port_hash_invariant_under_input_edge_iteration_order(subtract_spec):
    """Two edges into a multi-input node — hash sorts them; iteration-order can't perturb."""
    ...
def test_disabled_single_input_node_passes_parent_hash_through(linear_spec): ...
def test_disable_multi_input_raises(subtract_spec): ...
def test_deterministic_through_propagates_in_branches(linear_spec, noise_spec): ...
def test_to_dict_from_dict_round_trip(linear_spec, subtract_spec): ...
def test_from_dict_with_unknown_plugin_raises(linear_spec): ...
def test_undo_redo_add_node(linear_spec): ...
def test_undo_redo_connect(linear_spec): ...
def test_undo_redo_set_params(linear_spec): ...
def test_undo_after_set_tap_restores_previous_tap(linear_spec): ...
```

### 9b — graph executor

```python
# tests/test_graph_executor.py
def test_empty_graph_taps_source_inline_emits_raw(qtbot, sample_volume): ...
def test_three_node_linear_chain_matches_m5_compute(qtbot, sample_volume, linear_spec):
    """Build A→B→C as a graph; tap C; assert numerically equal to M5 chain output."""
    ...
def test_subtract_node_emits_a_minus_b(qtbot, sample_volume, linear_spec, subtract_spec): ...
def test_branch_cache_isolation(qtbot, sample_volume, linear_spec):
    """A→B and A→C; warm both; edit B's params; C's cache stays warm; C still tap-warm."""
    ...
def test_diamond_graph_executes_each_branch_once(qtbot, sample_volume, linear_spec):
    """A → B & A → C → both into D. A and C run once each; B runs once; D runs once."""
    ...
def test_tap_switch_to_cached_port_under_50ms(qtbot, sample_volume, linear_spec): ...
def test_cancel_on_new_request_drops_pending_nodes(qtbot, sample_volume, slow_spec): ...
def test_non_deterministic_node_poisons_downstream_branch(qtbot, sample_volume, noise_spec, linear_spec):
    """Sibling branch unaffected; only the cone-through-noise loses cache."""
    ...
def test_plugin_failure_halts_plan_and_emits_failed(qtbot, sample_volume, raising_spec): ...
def test_orphan_input_port_blocks_run(qtbot, sample_volume, subtract_spec):
    """subtract.a wired but subtract.b unwired ⇒ tapping subtract.out raises a clear error."""
    ...
def test_timeslice_axis_taps_source_timeslice_port(qtbot, sample_volume, linear_spec): ...
```

### 9c — canvas (qtpynodeeditor path)

```python
# tests/test_graph_canvas.py
@pytest.mark.skipif(not qtpynodeeditor_available, reason="canvas fallback")
def test_add_plugin_creates_canvas_node(qtbot, registry_with_envelope): ...
def test_wire_creates_edge_via_scene_api(qtbot, registry_with_envelope, registry_with_subtract): ...
def test_cycle_pre_check_blocks_wire_and_status_messages(qtbot):
    """Verify Graph.has_cycle_if_added pre-check rejects before scene.create_connection."""
    ...
def test_libs_cycle_exception_caught_and_dangling_cleaned(qtbot):
    """Belt-and-braces: even if pre-check missed, ConnectionCycleFailure is handled."""
    ...
def test_delete_node_removes_from_scene_and_graph(qtbot): ...
def test_ctrl_z_undoes_last_op(qtbot): ...
def test_output_port_double_click_sets_tap(qtbot): ...
def test_input_port_double_click_taps_delegated_source(qtbot):
    """Double-click an input port of B — should tap A.out (B's incoming source)."""
    ...
def test_set_in_data_does_not_emit_data_updated(qtbot):
    """Regression for the view-less / data-propagation NPE — our nodes must not fire propagation."""
    ...
```

All canvas tests instantiate `FlowView(scene)` even though they don't `.show()`, to avoid the connection-deletion NPE noted in Step 0.

If the spike fell through, replace with `tests/test_dock_fallback.py` covering the M5 list-dock variant with port-cell columns.

### 9d — wiring

```python
# tests/test_graph_app.py
def test_param_change_recomputes_only_affected_branch(qtbot, demo_project_path): ...
def test_open_two_surveys_each_keeps_own_graph(qtbot, demo_project_path): ...
def test_close_and_reopen_canvas_dock_preserves_graph(qtbot, demo_project_path): ...
```

### 9e — GUI smoke

Extend `tests/test_gui_smoke.py`:

```python
def test_graph_e2e_subtract(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume)

    from eggseis.builtins.envelope import envelope
    from eggseis.builtins.ormsby_bandpass import ormsby_bandpass
    from eggseis.builtins.subtract import subtract

    g = win._graphs[win._active_survey_id]
    bp = g.add_node_from_spec(ormsby_bandpass._eggseis_spec)
    en = g.add_node_from_spec(envelope._eggseis_spec)
    sub = g.add_node_from_spec(subtract._eggseis_spec)
    g.connect(Edge(SOURCE_ID, "inline", bp, "trace"))
    g.connect(Edge(SOURCE_ID, "inline", en, "trace"))
    g.connect(Edge(en, "out", sub, "a"))
    g.connect(Edge(bp, "out", sub, "b"))
    g.set_tap(sub, "out")

    with qtbot.waitSignal(win._executor.tapReady, timeout=10_000):
        win._request_tap()
    assert win.section_viewer.has_overlay
```

### Test conventions

- Reuse `linear_spec`, `slow_spec`, `noise_spec`, `raising_spec` from M4/M5.
- New `subtract_spec` fixture in `tests/conftest.py`: `@graph_node(inputs=("a","b"))` → `a - b`.
- New `make_graph(specs, edges=...)` factory: terse builder for compositional tests.
- `clear_registry()` autouse pattern still required.
- Cycle detection: prefer `pytest.raises(CycleError, match="...")` over generic ValueError checks.

## Step 10: CLI / docs

- No new CLI commands. `eggseis info` and `eggseis dump-inline` keep their synchronous single-attribute paths.
- `docs/plugin-authoring.md`: new section "Multi-input plugins" — example `subtract`, port-name semantics, why disable is illegal for multi-input. Existing trace_attribute material untouched.
- `docs/development.md`: new section "How graphs work in the GUI" — per-survey scope, port_hash cone math, lazy recompute, tap-anywhere mechanics, layout (canvas central, viewer dock). Link from README.
- README status: add line under M5 — `M6: graph-based plugin DAG — visual canvas, multi-input, tap any port.`
- CHANGELOG: `[v0.1.0a6]` entry summarising graph + canvas + multi-input + decorator generalisation.

## Step 11: Status surface

- Status bar: `"Computing {nodes_done}/{total_cold}: {plugin_name}…"` while the executor is mid-plan. Clears on `tapReady`.
- `Help → Compute Errors` (from M4) gains columns for `node_id` + plugin name + offending port. Branch-affecting errors keep the cone path in the error tooltip.
- Canvas: a node whose last execution failed gets a red badge in its title bar; clicking the badge clears it.
- No cache-hit-rate UI. No graph-stats dock. Same stance as M4/M5.

---

## Execution order

0. **Canvas spike — DONE.** `qtpynodeeditor 0.3.3` cleared on macOS; Linux/Windows CI smoke import folded into Step 1's first CI run.
1. `eggseis.graph` package skeleton + `Graph`, `Node`, `Edge` + `port_hash` + cycle detection. Tests for hash stability, cycle rejection, undo/redo (Step 9a). No Qt yet. Add `qtpynodeeditor>=0.3.3` to `gui` extra in `pyproject.toml`.
2. Generalise `PluginSpec` with `inputs` field. Migrate `trace_attribute` to populate it. Add `graph_node` decorator. Tests for back-compat (M3/M5 plugin tests still pass).
3. Build `subtract` built-in plugin + a `tests/builtins/test_subtract.py`.
4. Extend `JobOrchestrator.request` with `input_sections`. Single-input callers continue to work (verified by existing M4 tests).
5. `GraphExecutor` — start with the all-cached fast path. Test it. Then linear-chain M5 equivalence test. Then branching diamond. Then multi-input subtract. Then cancellation. Then determinism. (Steps 9b incremental.)
6. Build the canvas widget against the spike's chosen library; tests under `QT_QPA_PLATFORM=offscreen` (Step 9c).
7. Build `ParamDock` reusing M5's magicgui factory; trivial tests.
8. Wire into `MainWindow`; relayout; extend `tests/test_gui_smoke.py` (Step 9e).
9. Status surface + error log integration.
10. CHANGELOG, README, docs cross-links, plugin-authoring multi-input section.
11. `./scripts/test.sh ci` green on all three platforms.

Estimate: five-to-six weekends if disciplined. Largest unknowns concentrate on Step 0 (lib viability) and Step 6 (Qt edge cases on cycle snap-back, port-click signals, undo wiring against an upstream lib's own undo stack).

---

## Risks

- **Canvas spike fails or `qtpynodeeditor` destabilises mid-milestone.** Spike cleared on macOS — Linux + Windows CI is the remaining unknown. If either platform fails to import the lib under PySide6 6.11+, fall back to the list-dock-with-port-columns plan; ship DAG topology + multi-input + tap-on-port without the visual canvas. ROADMAP authorises this. Mark "v1.1: visual canvas" in ROADMAP and CHANGELOG. Do not let the canvas hold up M7.
- **`qtpynodeeditor`'s data propagation interferes with us.** The lib eagerly walks downstream on every wire change, calling `set_in_data` and triggering graphics-object work. Our nodes must override `set_in_data` to a no-op and never emit `data_updated`. Add a regression test (Step 9c) that subclassing `_PluginNode` does not accidentally emit through the lib. If a future lib version makes propagation harder to suppress, monkey-patch `Connection.propagate_data` to a no-op inside `eggseis.graph.canvas` init.
- **`qtpynodeeditor` cycle detection leaves dangling state.** The spike confirmed `ConnectionCycleFailure` raises but the failed wire stays in `port.connections`. Mitigation already in plan: pre-validate cycles via `Graph.has_cycle_if_added` before calling `scene.create_connection`. Belt-and-braces: catch the exception and walk the affected port's `.connections` list to remove the orphan reference. Tested in `test_libs_cycle_exception_caught_and_dangling_cleaned`.
- **Port-hash drift.** Renaming/restructuring the digest after M6 ships breaks any disk persistence that lands later. Lock the canonical-JSON layout in `port_hash` with a comment + hash-of-known-fixture test, the same defensive move M4 made for params_hash. Don't change the fold function without a major version bump.
- **Multi-input wait deadlocks.** The executor must guard against a cold node never becoming runnable (e.g. unconnected input port) — check upfront in `request_tap` and emit `failed` with a clear "node X port a is unconnected" message. Tested in `test_orphan_input_port_blocks_run`.
- **Stale orchestrator events after cancel.** Same defence as M5 (job_id mismatch). Now multiplied across N concurrent edges — a cancelled plan may have several in-flight orchestrator jobs. Ensure cancel disconnects all per-step slots, not just the most recent. Add a stress test that fires `request_tap` 20× rapidly and asserts no extra `tapReady` signals leak.
- **`qtpynodeeditor` has no undo stack of its own.** Means our `Graph.undo()` is the only source of truth — good for simplicity, but Ctrl+Z must be wired explicitly on the canvas widget; the lib will not handle it for us. Smoke-test that the keyboard shortcut reaches our handler before any QGraphicsScene default handling.
- **Multi-output plugins requested mid-M6.** Defer firmly. Document that v1.0 nodes have one output and that `crossplot_pair` ships in M9 with single-output for now. Adding multi-output later is a strict superset and won't break any M6 graphs.
- **Param widget lifecycle on node delete.** Same risk as M5's dock; same mitigation — `ParamDock` releases magicgui widgets on `RemoveNode`. Smoke test: add and remove 50 nodes; assert no widget leaks via `gc.collect()` count.
- **Demo flakiness.** Canvas tests rely on simulated mouse drags — keep them small and deterministic. Test cycle snap-back via the public `Graph.has_cycle_if_added` directly, not via the canvas widget, to avoid Qt-event-fragility.
- **M7 tension on serialisation.** `to_dict` / `from_dict` are M6 surfaces. M7 will write them into `project.yaml`. Keep the schema a flat dict-of-lists (not pickled, not custom-serialised) so YAML and JSON both accept it. No tuples in the serialised form; convert pos to list, version-tuple to list at the boundary.

---

## Out of scope for M6

- Multi-output plugin nodes — v1.1.
- Cross-tile-cross-node parallelism — measure first; v1.1 at the earliest.
- DAG persistence to disk — M7.
- Subgraphs, macros, encapsulation — out of scope for v1.0.
- Graph-level diff / version control — out of scope.
- Volume-wide compute — M9+ once the crossplot integration shows what's needed.
- Disk-backed cache — v1.1.
- Read-only sink nodes (histogram, stats display) — out of scope; everything in v1.0 emits a section-shaped ndarray.

---

## When M6 is done

A clean exit looks like:

- The user opens the F3 fragment, drags two nodes onto the canvas, wires Source.inline → bandpass.trace → envelope.trace, drops a `subtract` next to it, wires bandpass and envelope into its `a` and `b` ports, taps `subtract.out` — and sees the difference rendered in the section viewer.
- Editing one upstream node's params dirties only its branch; the sibling stays cache-warm; tap-warm port switches paint sub-50 ms.
- A cycle attempt produces a clear status-bar message and the wire snaps back. Disable on a multi-input node is greyed in the menu.
- `to_dict / from_dict` round-trips a non-trivial graph in tests.
- Headless tests cover model, executor, canvas (or fallback dock), serialisation, and an end-to-end multi-input GUI smoke.
- README, `docs/development.md`, `docs/plugin-authoring.md`, and CHANGELOG updated. `[v0.1.0a6]` tag prepared.
- Tag `v0.1.0a6` after the M6 PR merges.
- Take a beat. Then start M7 — "Horizons and wells."
