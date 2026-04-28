# eggseis — Development Roadmap

**Working document for the development of eggseis from pre-alpha through v1.0 public release.**

This roadmap captures the milestone plan and the design decisions behind it. It is intended to be edited as the project evolves — milestones may slip, scope may shift, and that's expected. What stays fixed is the discipline of shipping a demonstrable result every ~6 weeks.

---

## The North Star

A free, cross-platform desktop application for viewing and analyzing 3D seismic data, with a Python plugin system so simple that "write a new attribute" is a ten-line script.

**Primary user:** an industry geoscientist who scripts a little Python.

**Non-goals for v1.0:** anything that isn't necessary to deliver on the sentence above. The "Out of Scope" list is long and deliberate.

---

## Locked-in Design Decisions

These were settled during the design phase. Revisit them only with strong cause.

| Area | Decision |
|---|---|
| License | Apache 2.0 |
| Name | eggseis (PyPI reserved, GitHub org TBD) |
| Plugin language | Python only in v1.0 (C++/Rust via pybind11/PyO3 inside Python plugins) |
| Plugin tier | Trace-local (Tier 1) only in v1.0; API designed to extend to windows (Tier 2) without breaking changes |
| Plugin data model | NumPy arrays + context dict (lowest barrier for scripters) |
| Vectorization | Per-trace by default; opt-in `vectorized=True` flag |
| Storage backend | MDIO as the single backend; clean abstraction for future OpenVDS / TileDB |
| Project format | Plain directory on disk, YAML manifest, human-readable |
| Compute cache | In-memory LRU only in v1.0; disk cache deferred to v1.1 |
| UI toolkit | PySide6 (Qt) |
| Section viewer | pyqtgraph |
| Volume viewer | PyVista + VTK; three slicing planes default, full volume render opt-in |
| Crossplot | pyqtgraph + datashader (auto-switch above ~500K points) |
| Parameter UI | Pydantic schemas + magicgui widgets |
| Plugin composition | Linear chain in M5; full DAG with visual node-graph canvas in M6. Tap-anywhere inspection at every node/port. |
| Distribution | Micromamba-bundled conda-forge environment; signed installers per platform |
| Governance | BDFL (you) until phase 2 (~5 contributors); plan to evolve |

---

## Milestone Plan

Each milestone ends in something demonstrable. Estimates assume part-time evening/weekend effort; full-time is roughly 2x faster.

### M1 — "The data opens" *(weeks 1–4)*

**Deliverable:** A CLI that opens an MDIO survey, prints geometry, reads an inline, and saves it as a PNG. No UI yet.

**What gets built:**
- `pyproject.toml` and project skeleton (already done — placeholder is on PyPI).
- `eggseis.data.SeismicVolume` — the stable public abstraction. Properties: `geometry`, `shape`, `dtype`, `headers`. Methods: `read_inline()`, `read_xline()`, `read_timeslice()`, `read_trace()`, `read_traces()`, `read_window()`.
- `eggseis.backends.mdio.MDIOBackend` — the first (and for v1.0, only) backend.
- `eggseis.cli` — Typer or Click-based CLI with `eggseis info <survey>` and `eggseis dump-inline <survey> <inline_number>` commands.
- A test fixture that downloads a small real MDIO survey (F3 Netherlands fragment, or generate synthetic).
- CI on Linux/macOS/Windows running `pytest`.

**Exit criteria:**
- `eggseis info path/to/survey.mdio` prints inline range, xline range, sample rate, and basic stats.
- `eggseis dump-inline path/to/survey.mdio 1000 --output inline_1000.png` produces a PNG that visibly shows the seismic.
- Tests pass on all three platforms in CI.

**Why this matters:** the data layer is the foundation everything else rests on. Get it right here and you can build for a year on top of it without revisiting.

---

### M2 — "The section appears" *(weeks 5–8)*

**Deliverable:** A Qt application that opens a project, shows a list of surveys, and displays an inline in a pyqtgraph viewer with pan/zoom, colormap, and slice navigation.

**What gets built:**
- `eggseis.app` — main Qt application entry point.
- Project tree widget showing surveys, horizons (empty for now), wells (empty for now).
- Section viewer widget: pyqtgraph `ImageItem`, axis labels, crosshair readout, configurable colormap.
- Slice navigation: keyboard shortcuts and a spinbox to step through inlines/xlines/timeslices.
- Project loading: open a directory, parse `project.yaml`, populate the tree.
- Basic menu structure (File, View, Help).

**Exit criteria:**
- Launch the app, open a sample project, double-click a survey, see the section viewer.
- Pan, zoom, scroll through inlines, switch to xline view, switch to timeslice view — all responsive.
- Colormap can be changed from a menu.

**Why this matters:** this is the first moment the project has a face. You can demo it to a friend.

---

### M3 — "The plugin runs" *(weeks 9–14)*

**Deliverable:** A decorator-based plugin API. Drop a `my_bandpass.py` in a folder; it appears in the attribute menu; selecting it applies to the visible section. Parameters auto-generate a dialog.

**What gets built:**
- `eggseis.plugin` module — `@trace_attribute` decorator, `Param` class.
- Pydantic-based parameter schema — type, default, range, units, label, validators.
- magicgui-based parameter widgets — automatic Qt UI from the parameter declarations.
- Plugin discovery: scan `~/.eggseis/plugins/` and entry points, register decorated functions.
- Plugin execution path: when an attribute is selected, run it on the visible section traces and paint result.
- Five built-in plugins as public files (envelope, instantaneous phase, instantaneous frequency, RMS amplitude, Ormsby bandpass).
- "New Plugin" template wizard — File → New Plugin → opens an editor with a working skeleton.

**Exit criteria:**
- Author a new plugin in a separate file, drop it in the plugins folder, restart, see it in the menu.
- Selecting the plugin applies it to the section. Changing parameters in the dialog re-runs and updates.
- A second person (a friend, colleague, anyone) can write a working plugin in under 30 minutes given only the docs. **If they can't, the API isn't right yet — fix it before moving on.**

**Why this matters:** this is the wedge. The moment a non-you person can write a plugin and see it run is the moment the project has external value.

---

### M4 — "The compute feels good" *(weeks 15–20)*

**Deliverable:** The compute engine — worker threads, debounce, cancellation, in-memory cache, progressive tile delivery. Sliders update the section live; pan-and-return is instant.

**What gets built:**
- `eggseis.compute.JobOrchestrator` — `QThreadPool`-based worker scheduling.
- Debounce: 150ms timer that resets on each parameter change, fires once on quiet.
- Cancellation: cooperative tokens checked between trace batches; in-flight jobs canceled when superseded.
- Tile-level prioritization: viewport center first, then edges, then off-screen prefetch.
- Progressive delivery: workers emit results in batches every ~50ms, viewer paints as they arrive.
- In-memory LRU cache keyed by `(plugin_id, plugin_version, params_hash, slice_kind, slice_index, survey_version)`. Default ~500 MB.
- `vectorized=True` opt-in path: plugin receives a 2D batch, function called once per chunk instead of once per trace.
- Determinism flag (`deterministic=True` default) controlling cache eligibility.

**Exit criteria:**
- Drag a parameter slider on a slow attribute; UI stays responsive throughout; intermediate updates don't accumulate.
- Pan back to a previously-computed view; result appears in <50ms (cache hit).
- Run a vectorized plugin on a 1000×1500 section; total compute time under 1 second for typical SciPy operations.

**Why this matters:** this is when the product stops feeling like a prototype and starts feeling like software. Biggest perceived-quality leap in the whole roadmap.

---

### M5 — "The pipeline chains" *(weeks 21–23)*

**Deliverable:** A linear plugin pipeline. Stack two or more attributes on a survey, inspect the data at any node in the chain, edit a node's parameters and watch only the dirty downstream segment recompute.

**What gets built:**
- `eggseis.pipeline.Pipeline` and `Node` — append, remove, reorder, enable/disable, per-node param storage.
- `eggseis.pipeline_runner.run_up_to(pipeline, volume, axis, index, tap_node_id)` — execute through the tap, return the intermediate array.
- Stable per-node cache key: `hash(plugin_id, plugin_version, params, upstream_key)`. Reuses M4's in-memory LRU directly — no parallel cache.
- `PipelineDock` widget: list-style UI in the main window. Add (from discovered plugins), remove, drag-reorder, enable checkbox, per-row param editor, "tap" radio.
- Tap-on-disabled semantics: skip the node, return upstream output. Documented and tested.
- Section viewer binds to `(pipeline, tap_node_id)` instead of raw `read_inline`. Source = node 0 (always tap-able, raw amplitude).
- Headless tests covering: chain semantics, cache hit/miss, parameter-edit invalidates downstream only, tap-anywhere produces correct intermediate.

**Exit criteria:**
- Build a 3-node chain (e.g. `bandpass → envelope → rms_amplitude`); tap each node; section viewer shows that node's output.
- Edit `bandpass` parameters: nodes 2 and 3 recompute, node 1's prior outputs evicted, prior taps unaffected if same params reappear (cache reuse via M4 LRU).
- Disable middle node: chain skips it, downstream recomputes against upstream.
- Performance: tap switch on a cache-warm node paints in <50ms (inherits M4 cache hit budget).

**Why this matters:** turns plugins from "one-shot effects" into a workflow. Once a user can chain three attributes and inspect each, the tool starts to feel like an interpretation environment instead of a viewer.

**Out of scope (deferred to M6):** branching, multi-input nodes, visual node-graph canvas, persistence in `project.yaml` (M7 owns project save).

---

### M6 — "The graph branches" *(weeks 24–29)*

**Deliverable:** A real DAG. Visual node-graph canvas with draggable boxes and wired ports. Multi-input plugins (e.g. `subtract(a, b)`). Tap-on-port inspection at any output anywhere in the graph.

**What gets built:**
- DAG topology: nodes with N inputs and M outputs, topological execution order, cycle detection, dangling-input handling.
- `@graph_node(inputs=("a","b"), output="result")` — generalized decorator. `@trace_attribute` becomes the single-input shorthand and stays valid.
- Visual canvas widget: pan/zoom, multi-select, drag-to-wire, port-type checks (`np.ndarray` only in v1.0). Pick a library or hand-roll based on a one-week spike at milestone start: evaluate `qtnodes`, `node-editor`, `Qt-Node-Evaluator`, `pyflow`. Use one if it fits.
- Tap-anywhere extends to "tap any output port"; cache key chain extends naturally from M5 (each upstream port contributes its key).
- Per-node parameter editor docked alongside canvas (selection-driven).
- Headless tests for graph topology (cycles rejected, topo order correct, branch invalidation precise).

**Exit criteria:**
- Build a non-trivial graph: `bandpass → envelope` and `bandpass → instantaneous_phase`, both feeding a `crossplot_pair(x, y)` node; tap each port; outputs verified against direct compute.
- Canvas usability: drag, wire, multi-select, delete, undo/redo basic ops.
- Save/restore the graph round-trips (in-memory only in M6; project-file persistence remains M7).
- Cycle attempt fails loudly with a clear error message.

**Why this matters:** the moment the tool has a node graph, it stops being a section viewer and starts being a platform. This is also where attribute composition (the actual scientific workflow) becomes visible and editable.

**Risk note:** this is the single hardest milestone in the project. If the canvas spike at week 1 stalls, ship M6 with the M5 list-dock UI plus DAG topology (no visual canvas) and defer the canvas to v1.1. Branching DAG semantics matter more for v1.0 value than the canvas does.

---

### M7 — "Horizons and wells" *(weeks 30–35)*

**Deliverable:** Import and display horizons and wells on the section viewer. Project save/load round-trips correctly.

**What gets built:**
- Horizon importers: OpendTect ASCII, IHS grid, XYZ CSV.
- `eggseis.data.Horizon` abstraction — gridded surface stored as Zarr 2D array inside the survey container, with JSON sidecar for non-gridded attributes.
- Horizon overlay on section viewer: polyline intersected with the current slice, color-configurable.
- Well importers: LAS 2.0/3.0 via `lasio`, XYZ deviation surveys.
- `eggseis.data.Well` abstraction — HDF5 per well, log curves, deviation, markers.
- Well overlay on section viewer: deviated path traversing the section, log curves alongside.
- Header editor for surveys (display + correct trace header byte locations).
- Project save: write `project.yaml`, persist tree state, viewer state, currently-loaded plugins.
- Project load: round-trip the above without surprises.

**Exit criteria:**
- Import a horizon file, see it overlaid on the section in real time as you scroll inlines.
- Import a deviated well with logs, see it appear on intersecting sections with curves.
- Save the project, close the app, reopen — everything is exactly where you left it.

**Why this matters:** product becomes useful for real work, not just a demo. You can interpret with it (in a limited way) starting here.

---

### M8 — "The volume" *(weeks 36–41)*

**Deliverable:** PyVista volume viewer with three slicing planes, bounding box, horizon surfaces, well paths. Linked with the section viewer.

**What gets built:**
- `eggseis.viewers.volume` — PyVista `QtInteractor` widget embedded in the main window.
- Three orthogonal slicing planes (`vtkImagePlaneWidget`-style), draggable, with the rest of the cube clipped.
- Bounding box display showing the survey extent.
- Horizon surfaces: render imported horizons as 3D meshes with configurable shading.
- Well paths: render deviation surveys as polylines in the 3D scene.
- Linked cursor: hovering in the section viewer moves the crosshair in the volume viewer at the same coordinate, and vice versa.
- Camera controls: orbit, pan, zoom. Reset view, save/restore named camera positions.
- Full volume rendering as an opt-in mode (probably with downsampled overview, full-res on idle — keep it simple in v1.0).

**Exit criteria:**
- Open a survey, switch to the volume viewer, see three planes plus bounding box.
- Drag a slicing plane; corresponding section viewer (if open) moves to the matching slice.
- Toggle horizons on/off; meshes appear/disappear correctly.
- Performance feels fluid on a typical mid-sized survey (~5–20 GB).

**Why this matters:** the "wow" moment for any demo. Also validates the architecture supports more than one viewer.

---

### M9 — "The crossplot" *(weeks 42–47)*

**Deliverable:** pyqtgraph crossplot with header selection, lasso selection, linked highlighting in section and volume viewers. Datashader engages automatically above threshold.

**What gets built:**
- `eggseis.viewers.crossplot` — pyqtgraph-based scatter widget.
- Header / attribute picker for X axis, Y axis, color.
- Lasso and rectangle selection tools.
- Datashader integration: above ~500K points, aggregate to a density image rather than rendering individual points. Switch is automatic and invisible to the user.
- `eggseis.session.ViewerSession` — the central observable that coordinates all three viewers. Holds shared selection, cursor, active attribute, etc.
- Linked selection: lasso a cluster in the crossplot, watch the corresponding samples highlight in section and volume viewers.
- Density coloring for plain scatter mode.
- Save/restore named crossplot views in the project.

**Exit criteria:**
- Open a project with a horizon attribute, plot it against another header, see the points.
- Lasso a region; section viewer overlays the selected sample positions.
- Crank up the dataset size; rendering remains responsive past 10M points (datashader path).

**Why this matters:** rounds out the "three viewers" promise and proves the coordination layer works for richer interaction than just cursor linkage.

---

### M10 — "Alpha to real users" *(weeks 48–55)*

**Deliverable:** Cross-platform installers, signed builds, auto-update check, first-run demo project. Ship a private alpha to 5–10 geoscientists you know. Fix the embarrassing things they find.

**What gets built:**
- Conda-forge environment specification: pinned dependency set, lockfile per platform.
- Micromamba-based installer:
  - Windows: NSIS installer, code-signed (Authenticode).
  - macOS: `.dmg` with notarized app bundle. (Requires Apple Developer account, $99/year.)
  - Linux: AppImage and a conda-forge package.
- First-run flow: create default user plugin directory, drop demo project (F3 Netherlands fragment), open it.
- Auto-update *check* (not auto-install) — on launch, ping a manifest, surface "new version available" if newer.
- Crash reporting: structured error capture with plugin name, version, parameters, traceback.
- "Send Feedback" link in the Help menu.
- Documentation site (MkDocs Material): getting started tutorial, plugin author guide, API reference.
- Private alpha distribution: invite 5–10 specific people, weekly check-ins, ruthless triage of feedback.

**Exit criteria:**
- Five geoscientists install the app on their own machines (Windows + macOS coverage minimum) without your help.
- Each one runs through the demo project and writes at least one custom plugin.
- You collect a list of at least 20 issues from them and fix the top 10 before M11.

**Why this matters:** this is where you find out what you got wrong. You will have gotten something important wrong. Better to know at week 48 than week 96.

---

### M11 — "v1.0 public" *(weeks 56–61)*

**Deliverable:** Public release. GitHub repo polished, docs published, announcement on Software Underground / LinkedIn / blog. Five solid built-in attributes. A small registry of community plugins (even if seeded with 2–3 you wrote yourself).

**What gets built:**
- README polished with screenshots and a 30-second demo GIF.
- ROADMAP.md split out (a public version of this document).
- CHANGELOG.md starting from v1.0.
- CONTRIBUTING.md with the contributor flow (CLA setup, dev environment, "good first issues").
- Code of Conduct (Software Underground's, or Contributor Covenant).
- Plugin registry: a simple page on the docs site listing known community plugins with links to their PyPI / GitHub.
- Three "Good First Issue" plugins published as separate PyPI packages: `eggseis-ssa`, `eggseis-spectral`, `eggseis-geometric` (or whatever feels right).
- Announcement plan executed:
  - Software Underground Slack `#eggseis` channel announcement.
  - LinkedIn post (your network).
  - Blog post #1 of a series.
  - Conference abstract submitted (SEG, EAGE, or Transform — whichever timing aligns).
- v1.0.0 tagged release on GitHub with full release notes.

**Exit criteria:**
- The release ships. Real strangers download it. Some of them file issues. Some of them submit PRs.
- You've done at least one public talk or demo in the 30 days post-release.
- Year 2 of the project starts with momentum, not a void.

**Why this matters:** this is the goal.

---

## Out of Scope for v1.0

These are not bugs in v1.0 — they are deliberately deferred. Each one is a real feature; none is necessary for the v1.0 promise.

| Feature | Earliest target |
|---|---|
| Disk-backed compute cache | v1.1 |
| SEG-Y export | v1.1 |
| Window-based attributes (Tier 2) | v1.1 |
| Volume-to-volume transforms (Tier 3) | v1.2 |
| DLIS well import | v1.1 |
| Cloud object storage UI (S3, GCS) | v1.2 |
| Cross-domain plugins (horizon+seismic) | v1.2 |
| Horizon auto-tracking | v2.0 |
| Fault extraction | v2.0 |
| Spectral decomposition (built-in) | v2.0 |
| Prestack / gathers, 4D surveys | v2.0+ |
| Petrel / OpenWorks data exchange | v2.0+ |
| Manual interpretation tools (picking) | v2.0+ |
| Geomodeling, inversion, simulation | Out of scope indefinitely |
| Web/mobile deployments | Out of scope indefinitely |
| ML/AI plugins (built-in) | Community-driven, out of core indefinitely |

---

## Risks to Watch

These are the failure modes specific to a project like this:

1. **Perfection trap.** Domain expertise + open-source = constant urge to polish before shipping. Resist. Imperfect-and-shipped beats perfect-and-vapor every time.
2. **Audience drift.** Each "small" feature request from a different user persona is fine alone; collectively they destroy scope. Target user = "industry geoscientist who scripts a bit." Anyone else waits for v2.
3. **Solo-founder burnout.** 2+ years of evening/weekend work needs sustainable habits: dogfood the tool on real work, celebrate milestones publicly, take real breaks without guilt.
4. **One-company capture.** If a single sponsor becomes >50% of contributions, governance gets distorted. Diversify even when it costs short-term progress.
5. **Maintenance debt.** Post-v1.0, budget 20% of ongoing time for pure maintenance (dependency bumps, Python releases, Qt updates). Projects that ignore this die in year 2 or 3.

---

## What "Done with M1" Looks Like

To make the next concrete action obvious:

```bash
# Tonight or this weekend
$ git clone https://github.com/eggseis/eggseis.git
$ cd eggseis
$ python -m venv .venv && source .venv/bin/activate
$ pip install -e ".[dev]"
$ pytest
$ eggseis info tests/data/sample.mdio
Survey: F3 Netherlands (sample fragment)
  Inline range: 100–200
  Crossline range: 300–400
  Samples: 462
  Sample rate: 4 ms
  Format: float32

$ eggseis dump-inline tests/data/sample.mdio 150 --output inline_150.png
Wrote inline_150.png (1024×462, 0.4 MB)
```

That's M1 done. Everything else flows from there.

---

*This document is a living plan. Edit it as priorities shift — but be honest with yourself about why scope is changing each time you do.*
