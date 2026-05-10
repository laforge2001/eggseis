# Horizons as graph nodes — design

**Date:** 2026-05-01
**Status:** Approved during brainstorming; ready for implementation plan.
**Milestone:** M7+ (lands as part of M7 horizons-and-wells work or a follow-up)

## Goal

Make horizons first-class participants in the M6 plugin DAG: each horizon
appears as a small node on the canvas, associated by a dashed reference
edge with the Source. Overlay visibility on the section viewer is
controlled per-horizon (pin/unpin) and is independent of the compute tap.
Future plugins (e.g. a velocity flood) consume horizons as named
parameters — the dropdown is filtered by the horizon's Source membership.

## Decisions locked during brainstorming

| Question | Answer |
|---|---|
| When does the overlay render? | When the horizon's Source is in the upstream cone of the currently-tapped output (branch-scoped binding). For v1.0 — one Source per graph — this collapses to "any pinned horizon is visible" but the contract is locked now. |
| What does the dashed edge attach to? | The Source node. Only Source. |
| How is overlay visibility controlled? | Per-graph `pinned_overlays: set[node_id]`. Right-click horizon node → Pin/Unpin. Auto-pin on first add. Multiple horizons can be pinned simultaneously. Independent of the compute tap. |
| How do downstream plugins consume horizons? | Plugin declares a `Param` of type `HorizonRef` (or plain `str`). Param popup renders a dropdown filtered to "horizons whose Source is in this plugin's upstream cone." No new wire type, no port-type expansion. |
| How does the horizon node land on the canvas? | Right-click empty canvas → "Add Horizon" submenu listing `Project.horizons`. Pick one → node spawns at cursor + auto-creates the dashed Source edge + auto-pins the overlay. |
| How is the dashed line drawn? | `QGraphicsLineItem` owned by `GraphCanvas` — NOT a real qtpynodeeditor connection. Endpoints = bounding-rect centers of the horizon and Source scene nodes. Updates on `node_moved`. Cannot be drag-disconnected (no port endpoints). |

## Data model

### `eggseis.graph.model`

`Node` (existing dataclass) gains a non-breaking field:

```python
@dataclass
class Node:
    spec: PluginSpec | None        # None for horizon nodes
    params: BaseModel | None       # None for horizon nodes
    enabled: bool = True
    pos: tuple[float, float] = (0.0, 0.0)
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: Literal["plugin", "horizon"] = "plugin"
    horizon_name: str | None = None   # set when kind == "horizon"
```

Existing plugin nodes default to `kind="plugin"` so M6 callers stay
green. Horizon nodes set `kind="horizon"`, leave `spec`/`params=None`,
populate `horizon_name`.

`Graph` gains:

```python
@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]
    tap_port: tuple[str, str]
    associations: list[Association] = field(default_factory=list)
    pinned_overlays: set[str] = field(default_factory=set)
    ...
```

`Association(horizon_node_id: str, source_node_id: str)` is a frozen
dataclass; in v1.0 the source is always `SOURCE_ID`.

### Behaviour

- `Graph.add_horizon_node(horizon_name: str, *, pos) -> str` — adds the
  horizon node + creates the association + adds to `pinned_overlays`.
- `Graph.remove_node(node_id)` — for horizon nodes, also drops the
  association entry and the pin-set entry.
- `Graph.upstream_cone(node_id, port)` — UNCHANGED. Horizon nodes
  contribute nothing to compute, so they are not in any cone.
- `Graph.pin_overlay(node_id)` / `Graph.unpin_overlay(node_id)` — set/dict
  ops with validation that the node is `kind="horizon"`.
- `Graph.visible_horizons_for_tap(tap_node, tap_port) -> list[node_id]` —
  filters `pinned_overlays` by "is the associated Source in the upstream
  cone of `(tap_node, tap_port)`". For v1.0 this is "every pinned horizon
  whose Source = SOURCE_ID" (Source always in every cone). The function
  exists now to lock the contract for multi-source.

### `port_hash` / executor — UNCHANGED

Horizon nodes are pure declarations; they don't appear in the compute
graph. `_run_cold` ignores them.

## Canvas

### `GraphCanvas`

New responsibilities:

- **Add Horizon submenu.** When the user right-clicks empty canvas, the
  existing "Add Node" submenu gains an "Add Horizon" entry that opens a
  child menu listing `Project.horizons`. Selecting one calls
  `Graph.add_horizon_node(name)` and spawns the scene node at the cursor.
- **Horizon scene node.** Smaller body than plugin nodes. No port
  circles. Name shown as caption. A small `👁` icon overlays the body
  when the node is in `Graph.pinned_overlays`.
- **Dashed line.** `_horizon_lines: dict[str, QGraphicsLineItem]` keyed
  by horizon node_id. Pen: dashed, opacity 0.6, colour from
  `Horizon.color`. Endpoints recomputed from
  `scene_node.boundingRect().center()` for both endpoints whenever
  either node moves.
- **Move-update.** Hook `FlowScene.node_moved` (already emitted by the
  lib). Update every dashed line whose horizon or Source endpoint
  matches the moved node.
- **Right-click context menu** for horizon nodes:
  - "Pin overlay" / "Unpin overlay" toggle.
  - "Remove" — same code path as plugin remove.
- **Delete key** — same path as plugin delete; `Graph.remove_node`
  cleanup handles the association + pin set.

### `_make_horizon_scene_node`

Generated `NodeDataModel` subclass per horizon (or one shared subclass —
horizon nodes have no params or per-instance differentiation beyond the
name caption). One shared class is enough; the caption is updated per
instance.

## Persistence

`Graph.to_dict` extends:

```python
{
    "nodes": [
        {"node_id": ..., "kind": "plugin", "plugin_id": ..., "params": ..., ...},
        {"node_id": ..., "kind": "horizon", "horizon_name": "top_reservoir", "pos": [...]},
    ],
    "edges": [...],
    "tap_port": [...],
    "associations": [
        {"horizon_node_id": ..., "source_node_id": "source"},
    ],
    "pinned_overlays": ["nid1", "nid2"],
}
```

`Graph.from_dict` reads `kind`. For `kind="horizon"`, looks up
`horizon_name` in the registry passed in.

**API change:** `Graph.from_dict(d, registry)` becomes
`Graph.from_dict(d, *, plugins, horizons=None)` — two named registries.
`horizons` defaults to None for callers that don't have horizon nodes
in the graph (M6 callers, tests). Missing horizon → raises
`OrphanHorizonError` (parallel to `OrphanPluginError`). Update existing
M6 tests that call `from_dict(d, registry)` to use the keyword form.

## Section viewer integration

`MainWindow`:

- After any graph mutation (horizon add/remove, pin/unpin, tap change),
  call `_sync_horizon_overlays(graph)`:
  ```python
  visible = set(graph.visible_horizons_for_tap(*graph.tap_port))
  current = set(self.section_viewer.horizon_overlay_names())
  for nid in current - visible:
      self.section_viewer.remove_horizon_overlay(nid)
  for nid in visible - current:
      horizon = self._project.load_horizon(graph.nodes[nid].horizon_name)
      self.section_viewer.add_horizon_overlay(horizon)
  ```
- `Project.load_horizon(name)` is a small new helper that reads the
  `Horizon` from disk via `Project.horizons` lookup.

## Future plugin consumption (locked, deferred)

A plugin that consumes a horizon declares:

```python
@graph_node(name="Velocity Flood", inputs=("trace",))
def velocity_flood(
    trace: np.ndarray,
    horizon: str = Param(default="", choices=HorizonRef()),
    velocity_above: float = Param(default=2000.0),
    velocity_below: float = Param(default=3500.0),
) -> np.ndarray: ...
```

`HorizonRef` is a sentinel that the param-dock factory recognises. At
widget-build time it walks the plugin's upstream cone to find the
Source, collects horizon nodes associated with that Source, and renders
a dropdown of those names. At plugin-call time the runner resolves
`horizon` (a string) into a `Horizon` object via `Project.load_horizon`.

This consumption path is OUT OF SCOPE for this design's PR — it lands
when the first horizon-consuming builtin is shipped. The design locks
the shape so future work doesn't redesign it.

## Tests (named in advance)

- `test_horizon_node_added_to_graph_creates_association_and_pins`
- `test_horizon_node_serialises_with_kind_and_name`
- `test_orphan_horizon_on_load_raises`
- `test_pinned_overlays_round_trip_through_to_dict`
- `test_pin_unpin_updates_section_viewer_overlays`
- `test_remove_horizon_node_drops_association_and_pin`
- `test_horizon_node_excluded_from_upstream_cone`
- `test_visible_horizons_filters_by_source_in_cone` (locks the multi-source-future contract)
- `test_dashed_line_endpoints_update_on_node_move` (canvas-level)
- `test_add_horizon_submenu_lists_project_horizons` (canvas-level)

## Out of scope

- **Wells as graph nodes.** Symmetric design suggests wells should follow
  the same pattern; defer to a follow-up so this PR stays focused.
- **Multi-source graphs.** Each horizon associates with one Source. Locked
  here so M7's multi-source work picks up the contract correctly.
- **`HorizonRef` Param + first horizon-consuming plugin.** Locked above
  but not implemented.
- **Drag-from-tree-onto-canvas.** Add Horizon submenu is sufficient for
  v1.0; drag-drop is polish.
- **Per-horizon style editor.** Color is fixed at import; in-canvas
  recolouring is a separate feature.

## Risks

- **Dashed-line stutter on fast drag.** `node_moved` fires per pixel.
  Mitigation: throttle the line update via a 16 ms `QTimer` if profiling
  shows it.
- **Removing horizon from `Project.horizons`** while graphs reference it
  → `OrphanHorizonError` on next load. Mitigation: tree-side delete
  refuses when any open graph references the horizon, OR auto-removes the
  affected horizon nodes (pick at implementation time; cleaner path is
  the auto-remove).
- **On-disk graph compatibility.** `kind`, `associations`, and
  `pinned_overlays` all default safely (`"plugin"`, `[]`, `[]`), so
  reading an older M6 graph dict that lacks them works unchanged. No
  forced schema bump. The first `project.yaml` that contains horizon
  nodes will declare `schema_version: 2` (or stays at 1 if we decide
  the field-defaults pattern is enough). Decide at implementation time;
  the design doesn't force it either way. `migrations.py` already
  exists for the migration path if needed.
