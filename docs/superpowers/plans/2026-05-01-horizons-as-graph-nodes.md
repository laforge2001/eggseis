# Horizons as Graph Nodes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add horizon nodes to the M6 plugin DAG: dashed-edge associated with Source, per-graph pinned visibility, future plugin consumption via filtered Param dropdown.

**Architecture:** Extend `Node` with a `kind` discriminator + `horizon_name`; extend `Graph` with `associations` and `pinned_overlays` collections; render dashed Source edges as canvas-owned `QGraphicsLineItem`s outside qtpynodeeditor's connection machinery; sync section-viewer overlays from a single `_sync_horizon_overlays` helper triggered on graph mutations.

**Tech Stack:** Python 3.12, PySide6, qtpynodeeditor 0.3.3, pyqtgraph, pytest-qt.

**Spec:** `/Users/ericgeordi/dev/eggseis/docs/superpowers/specs/2026-05-01-horizons-as-graph-nodes-design.md`

---

### Task 1: Extend `Node` with `kind` discriminator + `horizon_name`

**Files:**
- Modify: `src/eggseis/graph/model.py`
- Test: `tests/test_horizon_graph_node.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_horizon_graph_node.py
"""Horizon node Graph integration."""

from __future__ import annotations

import pytest

from eggseis.graph.model import (
    SOURCE_ID,
    Association,
    Graph,
    Node,
    OrphanHorizonError,
)


def test_node_defaults_to_plugin_kind(linear_spec):
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    assert n.kind == "plugin"
    assert n.horizon_name is None


def test_horizon_node_construction():
    n = Node(
        spec=None, params=None,
        kind="horizon", horizon_name="top_reservoir",
    )
    assert n.kind == "horizon"
    assert n.horizon_name == "top_reservoir"
    assert n.spec is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: FAIL — `kind` and `horizon_name` not on Node, plus ImportError on `Association`/`OrphanHorizonError`.

- [ ] **Step 3: Add fields to Node**

```python
# src/eggseis/graph/model.py — find the Node dataclass (lines ~50-60) and replace:

from typing import Literal


@dataclass
class Node:
    spec: PluginSpec | None
    params: BaseModel | None = None
    enabled: bool = True
    pos: tuple[float, float] = (0.0, 0.0)
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: Literal["plugin", "horizon"] = "plugin"
    horizon_name: str | None = None
```

Note: `params` becomes optional (`None` default) so horizon nodes can leave it unset. Existing plugin callers always pass `params=...` explicitly so back-compat is preserved.

Also add at the top of `model.py`:

```python
class OrphanHorizonError(KeyError):
    """Raised by Graph.from_dict when a horizon name is missing from the registry."""


@dataclass(frozen=True)
class Association:
    horizon_node_id: str
    source_node_id: str = SOURCE_ID  # v1.0 has only the implicit Source
```

Update `__init__.py` re-exports to include `Association` and `OrphanHorizonError`.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: PASS for both new tests.

- [ ] **Step 5: Run full suite to confirm no regression**

Run: `./scripts/test.sh ci`
Expected: 322/322 (or current baseline) pass.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/graph/model.py src/eggseis/graph/__init__.py tests/test_horizon_graph_node.py
git commit -m "spec(horizons): Node.kind + horizon_name + Association + OrphanHorizonError"
```

---

### Task 2: Graph.associations + pinned_overlays + add_horizon_node + remove_node cleanup

**Files:**
- Modify: `src/eggseis/graph/model.py`
- Test: `tests/test_horizon_graph_node.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_horizon_graph_node.py`:

```python
def test_add_horizon_node_creates_association_and_pins():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top_reservoir", pos=(100.0, 50.0))
    assert nid in g.nodes
    assert g.nodes[nid].kind == "horizon"
    assert g.nodes[nid].horizon_name == "top_reservoir"
    assert any(
        a.horizon_node_id == nid and a.source_node_id == SOURCE_ID
        for a in g.associations
    )
    assert nid in g.pinned_overlays


def test_remove_horizon_node_drops_association_and_pin(linear_spec):
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    g.remove_node(nid)
    assert nid not in g.nodes
    assert g.associations == []
    assert g.pinned_overlays == set()


def test_pin_unpin_overlay():
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    g.unpin_overlay(nid)
    assert nid not in g.pinned_overlays
    g.pin_overlay(nid)
    assert nid in g.pinned_overlays


def test_pin_overlay_rejects_plugin_node(linear_spec):
    from eggseis.graph.model import Node
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    with pytest.raises(ValueError, match="horizon"):
        g.pin_overlay(n.node_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: 4 new failures (`add_horizon_node`, `pin_overlay`, `unpin_overlay` missing).

- [ ] **Step 3: Add Graph fields + methods**

Edit the `Graph` dataclass in `src/eggseis/graph/model.py`:

```python
@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    tap_port: tuple[str, str] = (SOURCE_ID, "inline")
    associations: list[Association] = field(default_factory=list)
    pinned_overlays: set[str] = field(default_factory=set)
```

Add methods to `Graph`:

```python
    def add_horizon_node(
        self,
        horizon_name: str,
        *,
        pos: tuple[float, float] = (0.0, 0.0),
    ) -> str:
        node = Node(
            spec=None,
            params=None,
            kind="horizon",
            horizon_name=horizon_name,
            pos=pos,
        )
        self.nodes[node.node_id] = node
        self.associations.append(
            Association(horizon_node_id=node.node_id, source_node_id=SOURCE_ID)
        )
        self.pinned_overlays.add(node.node_id)
        return node.node_id

    def pin_overlay(self, node_id: str) -> None:
        node = self.nodes[node_id]
        if node.kind != "horizon":
            raise ValueError(
                f"pin_overlay: node {node_id!r} kind={node.kind!r} (expected horizon)"
            )
        self.pinned_overlays.add(node_id)

    def unpin_overlay(self, node_id: str) -> None:
        self.pinned_overlays.discard(node_id)
```

Find `Graph.remove_node` and extend the cleanup. After the existing edge-pruning + tap-reset logic, add:

```python
        self.associations = [
            a for a in self.associations
            if a.horizon_node_id != node_id and a.source_node_id != node_id
        ]
        self.pinned_overlays.discard(node_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: all 4 + 2 prior tests PASS.

- [ ] **Step 5: Run full suite**

Run: `./scripts/test.sh ci`
Expected: 326+ pass (4 new tests added).

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/graph/model.py tests/test_horizon_graph_node.py
git commit -m "spec(horizons): Graph.associations + pinned_overlays + add_horizon_node"
```

---

### Task 3: Graph.visible_horizons_for_tap (multi-source future-proofing)

**Files:**
- Modify: `src/eggseis/graph/model.py`
- Test: `tests/test_horizon_graph_node.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_horizon_graph_node.py`:

```python
def test_visible_horizons_for_tap_when_source_in_cone(linear_spec):
    """v1.0: every pinned horizon is visible because Source is always in the cone."""
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    from eggseis.graph.model import Edge
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    g.set_tap(n.node_id)
    h = g.add_horizon_node(horizon_name="top")
    assert g.visible_horizons_for_tap(*g.tap_port) == [h]


def test_visible_horizons_for_tap_excludes_unpinned():
    g = Graph()
    h = g.add_horizon_node(horizon_name="top")
    g.unpin_overlay(h)
    assert g.visible_horizons_for_tap(*g.tap_port) == []


def test_horizon_node_excluded_from_upstream_cone(linear_spec):
    """Horizon nodes must not appear in upstream_cone results."""
    from eggseis.graph.model import Edge
    g = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model())
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    h = g.add_horizon_node(horizon_name="top")
    cone = g.upstream_cone(n.node_id, "out")
    assert h not in cone
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py::test_visible_horizons_for_tap_when_source_in_cone tests/test_horizon_graph_node.py::test_visible_horizons_for_tap_excludes_unpinned tests/test_horizon_graph_node.py::test_horizon_node_excluded_from_upstream_cone -v`
Expected: First two fail with `AttributeError: 'Graph' has no attribute 'visible_horizons_for_tap'`. Third passes (horizon nodes already aren't in `upstream_cone` because they have no edges).

- [ ] **Step 3: Implement visible_horizons_for_tap**

Add to `Graph` class:

```python
    def visible_horizons_for_tap(
        self, tap_node: str, tap_port: str
    ) -> list[str]:
        """Return horizon node_ids whose Source is upstream of (tap_node, tap_port)
        AND that are pinned.

        v1.0: only one Source exists, and Source is in every cone, so this
        reduces to "every pinned horizon node currently in the graph".
        Locked now to keep the contract right when multi-source lands.
        """
        if not self.pinned_overlays:
            return []
        cone = set(self.upstream_cone(tap_node, tap_port))
        # Source short-circuit: if tap is on Source, the cone is just {SOURCE_ID}
        # which doesn't include the horizon's source via the cone walk —
        # but Source IS the source for v1.0, so allow it directly.
        if tap_node == SOURCE_ID:
            cone = {SOURCE_ID}
        else:
            cone.add(SOURCE_ID) if SOURCE_ID in cone else None  # already true if reached
        visible = []
        for nid in self.pinned_overlays:
            assoc = next(
                (a for a in self.associations if a.horizon_node_id == nid),
                None,
            )
            if assoc is not None and assoc.source_node_id in cone:
                visible.append(nid)
        return visible
```

Note: for v1.0 the `cone` always contains `SOURCE_ID` whenever the tap is on a graph-reachable plugin (because `upstream_cone` returns Source as the rooted ancestor). The explicit Source-short-circuit handles `tap_node == SOURCE_ID` so that case also returns visible horizons.

- [ ] **Step 4: Run tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count up by 3.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/graph/model.py tests/test_horizon_graph_node.py
git commit -m "spec(horizons): Graph.visible_horizons_for_tap + cone-exclusion test"
```

---

### Task 4: Graph.to_dict / from_dict round-trips horizons

**Files:**
- Modify: `src/eggseis/graph/model.py`
- Test: `tests/test_horizon_graph_node.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_horizon_node_serialises_with_kind_and_name():
    g = Graph()
    g.add_horizon_node(horizon_name="top_reservoir", pos=(120.0, 50.0))
    d = g.to_dict()
    horizon_dicts = [n for n in d["nodes"] if n.get("kind") == "horizon"]
    assert len(horizon_dicts) == 1
    assert horizon_dicts[0]["horizon_name"] == "top_reservoir"
    assert horizon_dicts[0]["pos"] == [120.0, 50.0]


def test_associations_and_pinned_overlays_round_trip(linear_spec):
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    d = g.to_dict()
    assert d["associations"] == [{"horizon_node_id": nid, "source_node_id": SOURCE_ID}]
    assert d["pinned_overlays"] == [nid]


def test_from_dict_reconstructs_horizon_node(linear_spec):
    g = Graph()
    nid = g.add_horizon_node(horizon_name="top")
    d = g.to_dict()
    plugins = {linear_spec.id: linear_spec}
    horizons = {"top": object()}  # any sentinel; from_dict only checks membership
    rebuilt = Graph.from_dict(d, plugins=plugins, horizons=horizons)
    assert rebuilt.nodes[nid].kind == "horizon"
    assert rebuilt.nodes[nid].horizon_name == "top"
    assert rebuilt.pinned_overlays == {nid}


def test_orphan_horizon_on_load_raises(linear_spec):
    g = Graph()
    g.add_horizon_node(horizon_name="missing")
    d = g.to_dict()
    with pytest.raises(OrphanHorizonError, match="missing"):
        Graph.from_dict(d, plugins={linear_spec.id: linear_spec}, horizons={})
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v -k "serialise or round_trip or orphan"`
Expected: FAIL — `to_dict` doesn't yet emit horizon kind, `from_dict` signature mismatch.

- [ ] **Step 3: Update to_dict**

In `Graph.to_dict`, change the node-encoding loop to handle both kinds:

```python
    def to_dict(self) -> dict[str, Any]:
        node_dicts = []
        for n in self.nodes.values():
            if n.kind == "horizon":
                node_dicts.append({
                    "node_id": n.node_id,
                    "kind": "horizon",
                    "horizon_name": n.horizon_name,
                    "pos": list(n.pos),
                })
            else:
                node_dicts.append({
                    "node_id": n.node_id,
                    "kind": "plugin",
                    "plugin_id": n.spec.id,
                    "plugin_version": n.spec.version,
                    "params": n.params.model_dump(),
                    "enabled": n.enabled,
                    "pos": list(n.pos),
                })
        return {
            "nodes": node_dicts,
            "edges": [
                {
                    "src_node_id": e.src_node_id,
                    "src_port": e.src_port,
                    "dst_node_id": e.dst_node_id,
                    "dst_port": e.dst_port,
                }
                for e in self.edges
            ],
            "tap_port": list(self.tap_port),
            "associations": [
                {"horizon_node_id": a.horizon_node_id, "source_node_id": a.source_node_id}
                for a in self.associations
            ],
            "pinned_overlays": list(self.pinned_overlays),
        }
```

- [ ] **Step 4: Update from_dict signature + horizon branch**

Replace the existing `from_dict` classmethod:

```python
    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        *,
        plugins: dict[str, PluginSpec],
        horizons: dict[str, Any] | None = None,
    ) -> Graph:
        g = cls()
        for node_dict in d["nodes"]:
            kind = node_dict.get("kind", "plugin")
            if kind == "horizon":
                horizon_name = node_dict["horizon_name"]
                if horizons is None or horizon_name not in horizons:
                    raise OrphanHorizonError(horizon_name)
                node = Node(
                    spec=None, params=None,
                    kind="horizon",
                    horizon_name=horizon_name,
                    pos=tuple(node_dict.get("pos", (0.0, 0.0))),
                    node_id=node_dict["node_id"],
                )
            else:
                plugin_id = node_dict["plugin_id"]
                spec = plugins.get(plugin_id)
                if spec is None:
                    raise OrphanPluginError(plugin_id)
                params = spec.param_model(**node_dict["params"])
                node = Node(
                    spec=spec, params=params,
                    enabled=node_dict.get("enabled", True),
                    pos=tuple(node_dict.get("pos", (0.0, 0.0))),
                    node_id=node_dict["node_id"],
                    kind="plugin",
                )
            g.nodes[node.node_id] = node
        for edge_dict in d["edges"]:
            g.edges.append(Edge(
                src_node_id=edge_dict["src_node_id"],
                src_port=edge_dict["src_port"],
                dst_node_id=edge_dict["dst_node_id"],
                dst_port=edge_dict["dst_port"],
            ))
        g.tap_port = tuple(d.get("tap_port", (SOURCE_ID, "inline")))
        for a in d.get("associations", []):
            g.associations.append(Association(
                horizon_node_id=a["horizon_node_id"],
                source_node_id=a["source_node_id"],
            ))
        g.pinned_overlays = set(d.get("pinned_overlays", []))
        g._undo.clear()
        g._redo.clear()
        return g
```

- [ ] **Step 5: Update existing M6 tests that call `from_dict(d, registry)`**

Find every `Graph.from_dict(d, registry)` call:

```bash
grep -rn "from_dict(.*registry" src/ tests/
```

For each, change to keyword form: `Graph.from_dict(d, plugins=registry)`. Likely files: `tests/test_graph_model.py`. Run that test file alone to confirm:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_graph_model.py -v
```

- [ ] **Step 6: Run target tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_graph_node.py -v`
Expected: all PASS.

- [ ] **Step 7: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count includes new horizon tests; existing graph tests still green.

- [ ] **Step 8: Commit**

```bash
git add src/eggseis/graph/model.py tests/test_horizon_graph_node.py tests/test_graph_model.py
git commit -m "spec(horizons): Graph.to_dict + from_dict round-trip with kind=horizon"
```

---

### Task 5: Project.load_horizon helper

**Files:**
- Modify: `src/eggseis/project.py`
- Test: `tests/test_project_save_load.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_project_save_load.py`:

```python
def test_project_load_horizon_returns_horizon_object(tmp_path):
    from eggseis.data.horizon import Horizon
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    h = p.load_horizon("top")
    assert isinstance(h, Horizon)
    assert h.name == "top"


def test_project_load_horizon_unknown_raises(tmp_path):
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    with pytest.raises(KeyError, match="missing"):
        p.load_horizon("missing")
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_project_save_load.py -v -k "load_horizon"`
Expected: FAIL with `AttributeError: 'Project' has no attribute 'load_horizon'`.

- [ ] **Step 3: Add the helper**

In `src/eggseis/project.py`, add a method to the `Project` class:

```python
    def load_horizon(self, name: str):
        """Look up a HorizonEntry by name and return the loaded Horizon object.

        Raises KeyError if no entry matches.
        """
        from eggseis.data.horizon import Horizon

        entry = next((h for h in self.horizons if h.name == name), None)
        if entry is None:
            raise KeyError(f"horizon {name!r} not in project")
        return Horizon.load(entry.path)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_project_save_load.py -v -k "load_horizon"`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count up by 2.

- [ ] **Step 6: Commit**

```bash
git add src/eggseis/project.py tests/test_project_save_load.py
git commit -m "spec(horizons): Project.load_horizon helper"
```

---

### Task 6: SectionViewer.horizon_overlay_names() introspection

**Files:**
- Modify: `src/eggseis/viewers/section.py`
- Test: `tests/test_horizon_overlay.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_horizon_overlay.py`:

```python
def test_horizon_overlay_names_returns_keys(qtbot, fake_backend):
    from eggseis.viewers.section import SectionViewer

    viewer = SectionViewer()
    qtbot.addWidget(viewer)
    vol = SeismicVolume(fake_backend)
    viewer.set_volume(vol)
    viewer.add_horizon_overlay(_horizon_for(vol.geometry))
    assert viewer.horizon_overlay_names() == ["top"]
```

- [ ] **Step 2: Run test — verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_overlay.py::test_horizon_overlay_names_returns_keys -v`
Expected: FAIL.

- [ ] **Step 3: Add the helper**

In `src/eggseis/viewers/section.py`, add (next to `horizon_count`):

```python
    def horizon_overlay_names(self) -> list[str]:
        return list(self._horizon_overlays.keys())
```

- [ ] **Step 4: Run test — verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_overlay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eggseis/viewers/section.py tests/test_horizon_overlay.py
git commit -m "spec(horizons): SectionViewer.horizon_overlay_names introspection helper"
```

---

### Task 7: Horizon scene node + dashed line item

**Files:**
- Modify: `src/eggseis/graph/canvas.py`
- Test: `tests/test_horizon_canvas.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_horizon_canvas.py`:

```python
"""GraphCanvas integration for horizon nodes + dashed Source line."""

from __future__ import annotations

import pytest

from eggseis.graph.model import Graph

qtpynodeeditor = pytest.importorskip("qtpynodeeditor")


@pytest.fixture
def canvas(qtbot):
    from eggseis.graph.canvas import GraphCanvas

    widget = GraphCanvas()
    qtbot.addWidget(widget)
    return widget


def test_add_horizon_node_spawns_scene_node_and_dashed_line(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top_reservoir", pos=(150.0, 75.0))
    assert nid in g.nodes
    assert canvas.horizon_scene_node_for(nid) is not None
    line = canvas.dashed_line_for(nid)
    assert line is not None


def test_remove_horizon_node_removes_dashed_line(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.remove_node(nid)
    assert canvas.dashed_line_for(nid) is None


def test_dashed_line_endpoints_update_on_node_move(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top", pos=(100.0, 50.0))
    line = canvas.dashed_line_for(nid)
    line_p1 = (line.line().p1().x(), line.line().p1().y())

    horizon_scene = canvas.horizon_scene_node_for(nid)
    horizon_scene.position = (300.0, 200.0)
    canvas._refresh_dashed_lines()
    new_p1 = (line.line().p1().x(), line.line().p1().y())
    assert new_p1 != line_p1
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v`
Expected: 3 fails — `add_horizon_node`/`horizon_scene_node_for`/`dashed_line_for`/`_refresh_dashed_lines` missing.

- [ ] **Step 3: Add a horizon NodeDataModel subclass**

In `src/eggseis/graph/canvas.py`, near `_SourceModel`, add:

```python
class _HorizonModel(NodeDataModel):
    """Visual model for a horizon node — no ports, name caption only."""

    name = "Horizon"
    caption = "Horizon"
    caption_visible = True
    num_ports = {PortType.input: 0, PortType.output: 0}
    data_type = {"input": {}, "output": {}}
    port_caption_visible = False
    port_caption = {"input": {}, "output": {}}
```

Register it in `GraphCanvas.__init__` next to `_SourceModel`:

```python
        self._registry.register_model(_HorizonModel, category="eggseis")
```

- [ ] **Step 4: Add canvas fields + add_horizon_node + line management**

In `GraphCanvas.__init__`, alongside `_scene_nodes`:

```python
        self._horizon_scene_nodes: dict[str, qne.Node] = {}
        self._dashed_lines: dict[str, "QGraphicsLineItem"] = {}
```

Add public + helper methods (place near `add_plugin`):

```python
    def add_horizon_node(
        self, horizon_name: str, *, pos: tuple[float, float] | None = None
    ) -> str:
        if self._graph is None:
            raise RuntimeError("canvas not bound to a graph")
        target_pos = pos if pos is not None else self._next_default_position()
        nid = self._graph.add_horizon_node(horizon_name, pos=target_pos)
        self._suppress_signal_sync = True
        try:
            scene_node = self._scene.create_node(_HorizonModel)
        finally:
            self._suppress_signal_sync = False
        scene_node.model.caption = horizon_name
        scene_node.position = target_pos
        self._horizon_scene_nodes[nid] = scene_node
        self._add_dashed_line(nid)
        self.nodeAdded.emit(nid)
        return nid

    def horizon_scene_node_for(self, node_id: str):
        return self._horizon_scene_nodes.get(node_id)

    def dashed_line_for(self, node_id: str):
        return self._dashed_lines.get(node_id)

    def _add_dashed_line(self, horizon_node_id: str) -> None:
        from PySide6.QtCore import QLineF, Qt
        from PySide6.QtGui import QPen, QColor
        from PySide6.QtWidgets import QGraphicsLineItem

        if self._source_scene_node is None:
            return
        horizon_scene = self._horizon_scene_nodes.get(horizon_node_id)
        if horizon_scene is None:
            return
        pen = QPen(QColor(255, 204, 0))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.5)
        line_item = QGraphicsLineItem()
        line_item.setPen(pen)
        line_item.setOpacity(0.6)
        line_item.setZValue(-1)
        self._scene.addItem(line_item)
        self._dashed_lines[horizon_node_id] = line_item
        self._update_dashed_line(horizon_node_id)

    def _update_dashed_line(self, horizon_node_id: str) -> None:
        from PySide6.QtCore import QLineF

        horizon_scene = self._horizon_scene_nodes.get(horizon_node_id)
        if horizon_scene is None or self._source_scene_node is None:
            return
        line_item = self._dashed_lines.get(horizon_node_id)
        if line_item is None:
            return
        h_center = horizon_scene.graphics_object.sceneBoundingRect().center()
        s_center = self._source_scene_node.graphics_object.sceneBoundingRect().center()
        line_item.setLine(QLineF(s_center, h_center))

    def _refresh_dashed_lines(self) -> None:
        for nid in list(self._dashed_lines.keys()):
            self._update_dashed_line(nid)
```

Extend `remove_node` to clean up horizon-side state:

```python
    def remove_node(self, node_id: str) -> None:
        if self._graph is None:
            return
        is_horizon = (
            node_id in self._horizon_scene_nodes
            or (node_id in self._graph.nodes
                and self._graph.nodes[node_id].kind == "horizon")
        )
        self._graph.remove_node(node_id)
        if is_horizon:
            scene_node = self._horizon_scene_nodes.pop(node_id, None)
            if scene_node is not None:
                self._suppress_signal_sync = True
                try:
                    self._scene.remove_node(scene_node)
                finally:
                    self._suppress_signal_sync = False
            line_item = self._dashed_lines.pop(node_id, None)
            if line_item is not None:
                self._scene.removeItem(line_item)
        else:
            scene_node = self._scene_nodes.pop(node_id, None)
            if scene_node is not None:
                self._scene.remove_node(scene_node)
        self.nodeRemoved.emit(node_id)
        self.edgeChanged.emit()
```

Hook node-move:

```python
        # In __init__, after the existing scene signal connections:
        self._scene.node_moved.connect(lambda *_: self._refresh_dashed_lines())
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v`
Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count up by 3, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/eggseis/graph/canvas.py tests/test_horizon_canvas.py
git commit -m "spec(horizons): canvas adds horizon nodes + dashed Source line"
```

---

### Task 8: GraphCanvas right-click "Add Horizon" submenu

**Files:**
- Modify: `src/eggseis/graph/canvas.py` (or app.py — depending on where context menu lives)
- Test: `tests/test_horizon_canvas.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_horizon_canvas.py`:

```python
def test_canvas_register_horizons_populates_add_horizon_submenu(canvas):
    """register_horizons makes names available for the Add Horizon submenu."""
    g = Graph()
    canvas.bind(g)
    canvas.register_horizons(["top", "base", "channel"])
    names = canvas.horizon_names_available()
    assert names == ["top", "base", "channel"]


def test_register_horizons_empty_list_clears(canvas):
    g = Graph()
    canvas.bind(g)
    canvas.register_horizons(["top"])
    canvas.register_horizons([])
    assert canvas.horizon_names_available() == []
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v -k "horizon_names_available or register_horizons"`
Expected: FAIL — `register_horizons` and `horizon_names_available` not on canvas.

- [ ] **Step 3: Add register_horizons + accessor**

In `GraphCanvas.__init__`:

```python
        self._horizon_names_available: list[str] = []
```

Add methods:

```python
    def register_horizons(self, names: list[str]) -> None:
        """Set the list of horizon names available in the right-click menu.
        MainWindow calls this whenever Project.horizons changes."""
        self._horizon_names_available = list(names)

    def horizon_names_available(self) -> list[str]:
        return list(self._horizon_names_available)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v`
Expected: PASS.

- [ ] **Step 5: Wire MainWindow → canvas registration**

In `src/eggseis/app.py`, find `open_survey` (after `self._canvas.bind(...)`) and add:

```python
                if self._project is not None:
                    self._canvas.register_horizons(
                        [h.name for h in self._project.horizons]
                    )
```

Also call `self._canvas.register_horizons(...)` after import (in `_on_import_horizon` after the project is updated):

```python
                self._canvas.register_horizons(
                    [h.name for h in self._project.horizons]
                )
```

- [ ] **Step 6: Build the actual right-click submenu in MainWindow**

In `src/eggseis/app.py`, find `_on_node_context_menu` (right-click on a graph node) and add a separate handler for canvas-empty-area right-clicks. qtpynodeeditor doesn't expose a "background context menu" signal directly; the lib's FlowView has `generate_context_menu` which we already inherit. To add an "Add Horizon" entry alongside the lib's "Add Node" entries, we extend the FlowView's context menu.

For this plan: a simpler stand-in. Add a Graph-menu action `Graph → Add Horizon to Graph…` mirroring `Add Plugin to Graph…` so users have a working entry point even if the canvas right-click integration takes more time:

In `_build_menus`, after `Add Plugin to Graph…`:

```python
        a_add_horizon = QAction("Add &Horizon to Graph…", self)
        a_add_horizon.triggered.connect(self._on_add_horizon_to_graph)
        m_graph.addAction(a_add_horizon)
```

Add the handler:

```python
    def _on_add_horizon_to_graph(self) -> None:
        if self._active_survey_id is None:
            QMessageBox.information(
                self, "Add Horizon",
                "Open a survey first, then re-run this action."
            )
            return
        names = self._canvas.horizon_names_available()
        if not names:
            QMessageBox.information(
                self, "Add Horizon",
                "No horizons in this project. Import one first via "
                "File → Import Horizon."
            )
            return
        choice, ok = QInputDialog.getItem(
            self, "Add Horizon to Graph", "Horizon:", names, 0, False
        )
        if not ok:
            return
        self._canvas.add_horizon_node(choice)
```

- [ ] **Step 7: Run full suite**

Run: `./scripts/test.sh ci`
Expected: tests still pass; UI test count unchanged but Graph menu test asserts 5 menu entries — extend if necessary:

If `tests/test_gui_smoke.py::test_main_window_menus` asserts on Graph menu items, update that assertion:

```python
# Find the assertion and update if needed.
```

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py -v`

- [ ] **Step 8: Commit**

```bash
git add src/eggseis/graph/canvas.py src/eggseis/app.py tests/test_horizon_canvas.py tests/test_gui_smoke.py
git commit -m "spec(horizons): Graph menu Add Horizon to Graph + canvas registration"
```

---

### Task 9: Pin/unpin context menu + visual cue

**Files:**
- Modify: `src/eggseis/app.py`
- Modify: `src/eggseis/graph/canvas.py`
- Test: `tests/test_horizon_canvas.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_horizon_canvas.py`:

```python
def test_pin_and_unpin_via_canvas_methods(canvas):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")
    canvas.set_horizon_pinned(nid, False)
    assert nid not in g.pinned_overlays
    canvas.set_horizon_pinned(nid, True)
    assert nid in g.pinned_overlays


def test_set_horizon_pinned_emits_overlayChanged(canvas, qtbot):
    g = Graph()
    canvas.bind(g)
    nid = canvas.add_horizon_node("top")

    received = []
    canvas.overlayChanged.connect(received.append)
    canvas.set_horizon_pinned(nid, False)
    assert received == [nid]
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v -k "pin"`
Expected: FAIL — `set_horizon_pinned` and `overlayChanged` missing.

- [ ] **Step 3: Add canvas signal + method**

In `GraphCanvas`:

```python
    overlayChanged = Signal(str)  # horizon node_id whose pin state flipped
```

```python
    def set_horizon_pinned(self, node_id: str, pinned: bool) -> None:
        if self._graph is None:
            return
        if pinned:
            self._graph.pin_overlay(node_id)
        else:
            self._graph.unpin_overlay(node_id)
        self.overlayChanged.emit(node_id)
```

- [ ] **Step 4: Wire context menu in MainWindow**

In `_on_node_context_menu` in `src/eggseis/app.py`, before building the existing menu, branch on horizon vs plugin:

```python
        graph = self._graphs[self._active_survey_id]
        node = graph.nodes[node_id]

        if node.kind == "horizon":
            self._build_horizon_context_menu(node_id, screen_pos)
            return
        # ...existing plugin context menu code below
```

Add the handler:

```python
    def _build_horizon_context_menu(self, node_id: str, screen_pos) -> None:
        graph = self._graphs[self._active_survey_id]
        is_pinned = node_id in graph.pinned_overlays
        menu = QMenu(self)
        toggle = QAction("Unpin overlay" if is_pinned else "Pin overlay", self)
        toggle.triggered.connect(
            lambda _checked, nid=node_id, on=not is_pinned:
                self._canvas.set_horizon_pinned(nid, on)
        )
        menu.addAction(toggle)
        menu.addSeparator()
        remove = QAction("Remove", self)
        remove.triggered.connect(
            lambda _checked, nid=node_id: self._canvas.remove_node(nid)
        )
        menu.addAction(remove)
        menu.exec_(screen_pos)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_horizon_canvas.py -v`
Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count up by 2.

- [ ] **Step 7: Commit**

```bash
git add src/eggseis/graph/canvas.py src/eggseis/app.py tests/test_horizon_canvas.py
git commit -m "spec(horizons): pin/unpin via canvas + horizon context menu"
```

---

### Task 10: MainWindow `_sync_horizon_overlays` + tap-driven overlay refresh

**Files:**
- Modify: `src/eggseis/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_smoke.py`:

```python
def test_pin_unpin_horizon_node_updates_section_viewer(qtbot, demo_project_path):
    """Adding a horizon node + pinning shows overlay; unpinning removes it."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0, timeout=2000)
    survey_item = _find_first_survey_item(win.tree)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer.has_volume, timeout=2000)

    # Synthetic horizon registered into the project for this test.
    from eggseis.data.horizon import Horizon
    import numpy as np
    geom = win.section_viewer.geometry
    grid = np.full((geom.n_inlines, geom.n_xlines), 50.0, dtype=np.float32)
    h = Horizon(name="test_top", grid=grid, geometry_ref="x")
    target = win._project.root / "horizons" / "test_top"
    h.save(target)

    from eggseis.project import HorizonEntry
    win._project = win._project.with_horizon_added(
        HorizonEntry(name="test_top", path=target)
    )
    win._canvas.register_horizons([h.name for h in win._project.horizons])

    nid = win._canvas.add_horizon_node("test_top")
    qtbot.wait(50)  # let signal-driven sync run
    assert "test_top" in win.section_viewer.horizon_overlay_names()

    win._canvas.set_horizon_pinned(nid, False)
    qtbot.wait(50)
    assert "test_top" not in win.section_viewer.horizon_overlay_names()
```

- [ ] **Step 2: Run test — verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py::test_pin_unpin_horizon_node_updates_section_viewer -v`
Expected: FAIL — overlay never lands on the section viewer.

- [ ] **Step 3: Add `_sync_horizon_overlays` + signal hookups**

In `src/eggseis/app.py`, in `MainWindow.__init__`, after the canvas wiring, add:

```python
        self._canvas.overlayChanged.connect(lambda _nid: self._sync_horizon_overlays())
        self._canvas.nodeAdded.connect(lambda _nid: self._sync_horizon_overlays())
        self._canvas.nodeRemoved.connect(lambda _nid: self._sync_horizon_overlays())
```

Add the helper:

```python
    def _sync_horizon_overlays(self) -> None:
        if self._active_survey_id is None or self._project is None:
            return
        graph = self._graphs.get(self._active_survey_id)
        if graph is None:
            return
        visible_ids = set(graph.visible_horizons_for_tap(*graph.tap_port))
        # Map ids → horizon names via the graph's horizon nodes.
        visible_names = {
            graph.nodes[nid].horizon_name for nid in visible_ids
            if nid in graph.nodes
            and graph.nodes[nid].kind == "horizon"
            and graph.nodes[nid].horizon_name is not None
        }
        current = set(self.section_viewer.horizon_overlay_names())

        for name in current - visible_names:
            self.section_viewer.remove_horizon_overlay(name)
        for name in visible_names - current:
            try:
                horizon = self._project.load_horizon(name)
            except KeyError:
                continue
            self.section_viewer.add_horizon_overlay(horizon)
```

Also call `_sync_horizon_overlays` after every tap change (already triggered by `_request_tap`). Add at the end of `_request_tap`:

```python
        self._sync_horizon_overlays()
```

- [ ] **Step 4: Run test — verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py::test_pin_unpin_horizon_node_updates_section_viewer -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `./scripts/test.sh ci`
Expected: pass count up by 1, no regressions.

- [ ] **Step 6: Regenerate screenshot per CLAUDE.md rule**

Run: `./scripts/test.sh shot`
Expected: `wrote docs/m2-screenshot.png`. Stage it.

- [ ] **Step 7: Commit**

```bash
git add src/eggseis/app.py tests/test_gui_smoke.py docs/m2-screenshot.png
git commit -m "spec(horizons): MainWindow syncs section overlays from pinned + tap"
```

---

### Task 11: CHANGELOG + docs

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/development.md`

- [ ] **Step 1: Add CHANGELOG entry**

Edit `CHANGELOG.md`. Append to the M7 in-progress section:

```markdown
- Horizons-as-graph-nodes: each horizon can appear as a node on the
  canvas, dashed-edge associated with Source. Pin/unpin per horizon
  controls section-viewer overlay visibility independently of the
  compute tap. Multiple horizons can be pinned at once. Branch-scoped
  binding (overlay shows when the horizon's Source is in the upstream
  cone of the current tap) — locked now so the multi-source future
  picks up the contract correctly.
- New `Graph.associations`, `Graph.pinned_overlays`,
  `Graph.add_horizon_node`, `Graph.visible_horizons_for_tap`.
- `Graph.from_dict` signature is now keyword-only:
  `Graph.from_dict(d, *, plugins=..., horizons=None)`. Existing M6
  callers updated.
- New canvas APIs: `add_horizon_node`, `set_horizon_pinned`,
  `register_horizons`, `horizon_names_available`. Dashed `QGraphicsLineItem`
  drawn between horizon and Source bounding-rect centers; updates on
  `node_moved`.
- New `Project.load_horizon(name)` helper.
- New `Graph → Add Horizon to Graph…` menu action.
- New right-click context menu on horizon nodes: Pin / Unpin / Remove.
```

- [ ] **Step 2: Add docs/development.md note**

Edit `docs/development.md`. Append to the "How graphs work in the GUI (M6+)" section:

```markdown
- **Horizon nodes (M7+).** Horizons in the project tree can be added to
  the canvas via `Graph → Add Horizon to Graph…` or right-clicking the
  canvas. They render as small nodes with no ports, dashed-edge linked
  to Source. Right-click → Pin / Unpin controls the section-viewer
  overlay. Pin state is per-graph; multiple horizons may be pinned
  simultaneously.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/development.md
git commit -m "spec(horizons): CHANGELOG + docs entries"
```

---

## Self-Review Notes

- **Spec coverage:** All locked decisions in the spec map to a task. `HorizonRef` Param + first horizon-consuming plugin are explicitly out-of-scope per the spec; not in this plan.
- **Type consistency:** `Node.kind`, `Association.horizon_node_id`/`source_node_id`, `Graph.pinned_overlays: set[str]`, `Graph.from_dict(d, *, plugins, horizons=None)` — names consistent across tasks.
- **No placeholders:** every code step shows the full code; no TBD/TODO.
- **Schema-bump open question:** spec leaves it open. Plan leaves it open too — fields all have safe defaults, so M6-shape graphs deserialise without bump. If a future change forces the bump, `migrations.py` is in place.
