# Changelog

All notable changes to eggseis are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [PEP 440](https://peps.python.org/pep-0440/).

## [0.1.0a7] — 2026-05-03

**M7 — "Horizons and wells" complete.**

### Added
- `eggseis.horizon` package: `Horizon` domain model + Zarr-backed I/O
  (`save_horizon`, `load_horizon`, list/delete helpers). Horizons store
  per-bin time/depth values plus optional attributes; on-disk schema is
  versioned (`horizon_schema_version`) for forward-compat.
- OpendTect ASCII (`.dat`) horizon importer — header-tolerant, IL/XL
  + Z columns, multi-attribute. Fits the v1.0 `Import Horizon…`
  workflow (academic + open-source datasets).
- XYZ CSV horizon importer retained as the lightweight path.
- Horizon overlay on the section viewer: per-horizon colour, pinned
  visibility, axis-aware projection (inline / xline / timeslice).
- Horizons-as-graph-nodes: each horizon can appear as a node on the
  canvas, dashed-edge associated with Source. Pin/unpin per horizon
  controls section-viewer overlay visibility independently of the
  compute tap. Multiple horizons can be pinned at once. Branch-scoped
  binding (overlay shows when the horizon's Source is in the upstream
  cone of the current tap) — locked now so the multi-source future
  picks up the contract correctly.
- New `Graph.associations`, `Graph.pinned_overlays`,
  `Graph.add_horizon_node`, `Graph.visible_horizons_for_tap`.
- New canvas APIs: `add_horizon_node`, `set_horizon_pinned`,
  `register_horizons`, `horizon_names_available`. Dashed
  `QGraphicsLineItem` drawn between horizon and Source bounding-rect
  centers; updates on `node_moved`.
- New `Graph → Add Horizon to Graph…` menu action and right-click
  context menu on horizon nodes (Pin / Unpin / Remove).
- `Project.load_horizon(name)` helper. Horizon import now works
  without an active survey (project tree right-click → Import
  Horizon…).
- `eggseis.well` package: `Well` + `WellLog` domain models, HDF5-backed
  I/O. Wells carry XYZ deviation + named log curves with units.
- LAS 2.0 / 3.0 importer with `LasImportError` taxonomy: alias-tolerant
  curve naming, `isclose`-based NULL handling, useful error messages on
  malformed sections. Hardened against the field LAS files we threw
  at it during M7.
- Well-path overlay on the section viewer: projects the well trajectory
  onto the current section with lateral-offset shading and a "not
  visible" warning banner when the well is too far from the slice to
  draw meaningfully.
- Well-log side panel beside the section viewer: per-well curve picker,
  shared depth/time axis, scrolls in lockstep with the section.
- Map view docked below the section viewer: top-down survey footprint
  with horizon outlines, well heads, and the current section's slice
  trace highlighted. Click-to-jump on well heads.
- Project save / load: full graph (nodes, edges, params, positions,
  pinned horizons, associations) + viewer state (active survey, axis,
  index, colormap, lock-levels, pinned wells/curves) round-trips
  through `project.yaml` + sidecar files. Schema versioned for
  forward-compat.
- Orphan-plugin / orphan-horizon recovery dialog on project load:
  surfaces missing referents with a per-item action (skip node, drop
  reference, abort load) instead of silently corrupting the graph.
- Project tree right-click "Load…" actions for horizons and wells —
  works without an active survey.
- In-memory header editor (Survey → Edit Trace Headers): per-trace
  IL / XL / coordinate edits with diff preview, undo, and an explicit
  Apply step. Edits stay in the session; persistence to disk is a
  future MDIO writer concern.
- Streaming volume export: `export_volume_with_graph` now writes
  chunked Zarr via `to_zarr(region=...)` instead of allocating the
  full output cube. Replaces the M6 8 GB in-memory cap with a
  bounded-memory chunked write.

### Changed
- `Graph.from_dict` signature is now keyword-only:
  `Graph.from_dict(d, *, plugins=..., horizons=None)`. Existing M6
  callers updated.
- Project schema bumped (`project_schema_version`, separate
  `horizon_schema_version` and `well_schema_version`); load path
  rejects unknown major versions and warns on unknown minor.
- `pyproject.toml` `gui` extra adds `lasio>=0.31` and `h5py>=3.10`
  for well I/O.

### Notes
- 397 tests at the M7 cut. CI matrix green across macOS / Ubuntu /
  Windows × Python 3.11 / 3.12.
- The M5 `eggseis.pipeline` package is still on disk so the M5 test
  suite keeps passing; the GUI no longer touches it. The scheduled
  remote agent (2026-05-14) will open the deletion PR.

### Known limitations (deferred)
- **Multi-source graphs** — deferred to v1.1 after benchmarking
  against industry tools (Petrel, OpendTect, PaleoScan all use
  single-volume pipelines + dedicated cross-survey tools); not the
  right shape for v1.0.
- **IHS grid binary horizon importer** — XYZ CSV + OpendTect ASCII
  covers most academic + open-source workflows.
- **Multi-curve well-log lanes** — single curve per panel today;
  multi-curve in a follow-up.
- **Drop M5 `eggseis.pipeline` package** — scheduled remote agent
  fires 2026-05-14; will open a cleanup PR.
- **Vertical port orientation on canvas** — qtpynodeeditor doesn't
  expose orientation; deferred to v1.1.
- **Streaming volume export RSS-during-init** — `to_zarr(compute=False)`
  still touches a placeholder ndarray during metadata serialisation;
  ~1.7 GB peak for a 13.5 GB target. Bounded but not zero.

## [0.1.0a6] — 2026-04-30

**M6 — "The graph branches" complete.**

### Added
- `eggseis.graph` package: `Graph`, `Node`, `Edge`, `CycleError`, `OrphanPluginError`, `GraphExecutor`, `GraphCanvas`, `GraphParamDock`, `SOURCE_ID`, `SOURCE_PORTS`.
- DAG topology with N-input / 1-output nodes and an implicit `Source` (id `"source"`) emitting raw section reads on three output ports `inline` / `xline` / `timeslice`. Cycles rejected at edge-creation time via DFS forward from the new edge's destination.
- `Graph.port_hash(node_id, port, volume_version, axis)` — blake2b digest of the upstream cone of an output port. Source ports key off `(volume_version, axis, port)`. Each enabled node folds in `(plugin_id, version, params_hash, sorted_input_port_hashes)`. Disabled single-input nodes pass parent's hash through (skip = identity); multi-input nodes can't be disabled.
- `@graph_node(*, name, version, inputs=("input",), deterministic=True)` decorator for multi-input plugins. `@trace_attribute` continues to work as the single-input shorthand and now populates `PluginSpec.inputs` from the vectorized flag (`"trace"` or `"traces"`).
- Built-in `subtract` plugin (`a, b → a - b`) — first multi-input attribute.
- `JobOrchestrator.request` accepts `input_sections=dict[port_name, ndarray]`. `compute_tile` slices each declared input by axis-0 `[start:stop]` and dispatches by port name. Single-input legacy callers still pass `input_section=arr`; the orchestrator normalises.
- `GraphExecutor(QObject)`: walks the upstream cone of the tap port, looks up each output's `port_hash` in the cache, topologically executes the cold subgraph. Multi-input nodes block advancement until every input port has a resolved array. Disabled identity-skip handled in a flat loop.
- `GraphCanvas(QWidget)` — `qtpynodeeditor`-backed visual node-graph. Pre-validates every wire against `Graph.has_cycle_if_added` (lib's `ConnectionCycleFailure` is a backstop with dangling-port cleanup). User-drag of a wire syncs into the model via `connection_created`/`connection_deleted` signals; suppress flag prevents echo when our own `connect_edge` mutates the scene first. Source node singleton, dynamic per-spec `NodeDataModel` subclass cached by plugin id, position round-trips through `bind()` after `to_dict`/`from_dict`. Selection emits a graph node id; double-clicking a node taps its `out` port.
- `MainWindow` rewired into a 3-pane layout: project tree (left) | section viewer + slice nav (center) | graph canvas (right) — all in one horizontal `QSplitter`. Empty-graph or Source-tap short-circuits to the section viewer's raw paint.
- `NodeParamsPopup` — modeless `QDialog` opened on canvas-node double-click. Multiple popups can stay open at once; `paramsChanged(node_id, params)` flows back to `Graph.set_params + _request_tap`. Survey-switch closes any leftover popups.
- Graph menu: **Add Plugin to Graph…** (input dialog over discovered plugins) and **Export Volume with Graph Applied…** (file dialog → `QProgressDialog` with cancel; iterates every inline through the synchronous runner and writes a new MDIO).
- Canvas right-click adds: every discovered plugin pre-registered into qtpynodeeditor's `DataModelRegistry` so the lib's built-in "Add Node" context menu lists the full library with filter + category tree. `node_created` signal mirrors lib-side adds back into `Graph`. Auto-tap on `nodeAdded` covers menu adds and right-click adds.
- Per-node right-click context menu (Enable / Disable / Tap output / Remove); multi-input nodes show Disable greyed (identity-skip is undefined).
- Delete-key removes selected nodes (lib's `delete_selection_action` rewired through `_install_delete_filter` so Source is excluded). Source stays movable + wireable + selectable for visual feedback; only the Delete shortcut filters it.
- `eggseis.graph.runner` — synchronous graph runner (no Qt, no orchestrator, no cache). `run_graph_on_section` walks the upstream cone topologically; `export_volume_with_graph` iterates every inline, hoists cone resolution, memoises Source-port reads per call, and writes a new MDIO. 8 GB in-memory cap protects against accidental OOM on large surveys.
- `save_section_npy` builtin — first **sink-kind** plugin: side-effects once at the section level (writes the input to a `.npy` file) and passes its input through unchanged. `PluginSpec.kind: Literal["transform", "sink"]` controls the executor + runner branching.
- `open_survey` shows a busy `QProgressDialog` + WaitCursor while MDIO opens (so the user sees feedback during the synchronous load); re-entry guard ignores rapid double-clicks.
- New synthetic demo datasets shipped alongside the existing `demo.mdio`: `examples/demo-project/wedge.mdio` (32×24×96, dipping reflectors + channel feature, Ricker-convolved) and `checkerboard.mdio` (20×16×80, alternating amplitude blocks). `scripts/build_demo_data.py` regenerates them.
- `examples/canvas_spike.py` — spike artefact validating qtpynodeeditor's multi-input + signals + cycle detection on PySide6 6.11 / Python 3.12.
- `M6-PLAN.md` documents the milestone, library spike findings, and outstanding follow-ups.

### Changed
- `PluginSpec` gains `inputs: tuple[str, ...]` (default `("trace",)`) and `output: str` (default `"out"`) fields. Decorators populate them; serialisation passes the value through.
- `Job.section` becomes a back-compat property reading `inputs[spec.inputs[0]]`. New code uses `Job.inputs: dict[str, np.ndarray]`.
- `pyproject.toml` `gui` extra adds `qtpynodeeditor>=0.3.3`. Per-file ruff ignores extended for `src/eggseis/graph/*.py` (Qt camelCase signals) and `src/eggseis/graph/canvas.py` (RUF012 — qtpynodeeditor `NodeDataModel` requires class-level dicts).

### Notes
- The M5 `eggseis.pipeline` package is retained on disk so the M5 test suite keeps passing, but the GUI no longer touches it. A scheduled remote agent (2026-05-14) checks orphan status and opens a deletion PR.
- DAG persistence to disk remains M7's concern. Multiple output ports per node, cross-tile-cross-node parallelism, multi-source graphs, vertical port orientation, and subgraphs are out of scope for v1.0.
- 282 tests at the M6 cut. CI matrix green across macOS / Ubuntu / Windows × Python 3.11 / 3.12.

### Known limitations (deferred)
- **Multi-source graphs.** One implicit Source per graph today. Cross-survey ops (e.g. subtract two different MDIO datasets) need a per-survey Source kind + multi-volume executor — M7 or v1.1.
- **Vertical port orientation.** qtpynodeeditor's per-node ports are fixed input-left / output-right. True top/bottom ports need subclassing `NodeGeometry` + `NodePainter` + connection-bezier math. Cascade direction matches port flow (rightward).
- **Streaming volume export.** `export_volume_with_graph` allocates the full output cube in RAM; surveys >8 GB raise `MemoryError`. Streaming write via `xr.Dataset.to_zarr(region=...)` is M7+.
- **Undo / redo keybind.** `Graph.undo()` / `Graph.redo()` exist but no `Ctrl+Z` shortcut on the canvas. Polish item.

## [0.1.0a5] — 2026-04-29

**M5 — "The pipeline chains" complete.**

### Added
- `eggseis.pipeline` package: `Pipeline`, `Node`, `PipelineExecutor`, `SOURCE_ID`.
- Per-survey linear pipelines retained for the session (lost on app quit; M7 owns disk persistence).
- `PipelineDock` widget (left dock area in `MainWindow`): list of nodes with enable checkbox + tap radio per row, selection-driven param panel, "+ Add plugin" picker.
- Tap-anywhere: section viewer binds to the tap node's output rather than a single attribute. Source row (always non-removable, top of dock) paints raw amplitude.
- `chain_hash`-keyed cache: each node's output is memoised with a Source-rooted hash so editing an upstream parameter invalidates only downstream nodes; revisiting the same params hits cache.
- `deterministic=False` poisons the chain downstream as well as itself: deterministic nodes after a non-deterministic one are excluded from cache reads and writes via a `skip_cache_write` flag on `Job`.
- Status bar surface: "Computing N of M: <plugin>…" while the executor is mid-plan; clears on `tapReady`.
- Headless tests: pipeline model invariants (`chain_hash_for`, `nodes_up_to_tap`, `deterministic_through`, set-tap defensive shift), executor behaviour (cold execution, warm tap, mid-chain edit, disabled skip, non-det poison, failure halt, timeslice short-circuit, supersede cancellation, progress emission), and a 3-node GUI smoke (`bandpass → envelope → rms_amplitude`).

### Changed
- `CacheKey.params_hash` renamed to `chain_hash` (semantic-only; helper `params_hash` still computes a params-only digest for single-attribute callers).
- `JobOrchestrator.request` accepts optional `input_section`, `chain_hash`, and `skip_cache_write` keyword arguments so the executor can drive it through a chain without re-reading the volume and without poisoning the cache for chain-level non-determinism.

### Notes
- Pipeline persistence to disk is intentionally deferred to M7.
- Branching, multi-input nodes, and the visual node-graph canvas are M6.
- Per-node param-widget integration with magicgui across multiple node instances is a known polish item; the dock currently falls back to an empty panel for nodes whose factory returns None.

## [0.1.0a4] — 2026-04-27

**M4 — "The compute feels good" complete.**

### Added
- `eggseis.compute` package: `JobOrchestrator` (`QObject`) owns a `QThreadPool`, a 150 ms debounce timer, a 50 ms progressive-delivery timer, and an in-memory `SectionLRU`. `request(spec, params, volume, axis, index)` is the single GUI entry point.
- `SectionLRU` — `OrderedDict`-backed byte-budgeted cache (default 500 MB; override with `EGGSEIS_CACHE_BYTES`). `CacheKey` includes `(plugin_id, plugin_version, params_hash, axis, index, volume_version)`; `params_hash` is a canonical-JSON blake2b digest stable across dict orderings. `deterministic=False` plugins skip the cache on both reads and writes.
- `Tile` + `split_section()` — center-out priority (visible middle of the section paints first).
- `TileRunnable` (`QRunnable`) + `TileSignals` (`QObject`) — single-tile workers with cooperative cancel checked between trace rows (scalar) or before each tile call (vectorized). Worker exceptions surface as a `failed(job_id, message)` signal.
- `Job` + `CancellationToken` — pure-Python primitives carrying spec/params/section/output/context/token per request.
- `SeismicVolume.version` + `MDIOBackend.version` — opaque tuple identity used as a cache-key input.
- `eggseis.plugin_runner.compute_tile()` — extracted trace-loop primitive shared by the synchronous CLI/library path and the new tile workers. `run_on_section` now delegates to it.
- `SectionViewer.set_overlay(arr, *, partial=False)` — partial paints reuse baseline percentile levels so the colour scale stays stable across in-progress emissions.
- `MainWindow` is wired to `JobOrchestrator`: `tilesReady` paints partials, `sectionReady` paints the final image, `failed` surfaces a status-bar message and aggregates into a session-scoped log shown via **Help → Compute Errors…**. The most recently emitted plugin params are cached so a slice change preserves the user's slider values instead of resetting to plugin defaults.
- `docs/development.md` gains a "Compute model (M4+)" section; `docs/plugin-authoring.md` gains a `deterministic=False` note.

### Changed
- `pyproject.toml` ruff per-file ignore extended to `src/eggseis/compute/*.py = ["N815"]` (Qt camelCase signal names follow the same rule as `widgets/` and `viewers/`).

### Notes
- Library/CLI behavior unchanged. `eggseis info`, `eggseis dump-inline`, and `eggseis plugins` continue to use synchronous `run_on_section`. The orchestrator is GUI-only.
- 129 tests at the M4 cut. CI matrix green across macOS / Ubuntu / Windows × Python 3.11 / 3.12.
- Pipeline chains (linear, M5) and DAG + canvas (M6) reuse the M4 cache via stable per-node keys; no parallel cache.

## [0.1.0a3] — 2026-04-27

**M3 — "The plugin runs" complete.**

### Added
- `eggseis.plugin` — `@trace_attribute` decorator + `Param` dataclass + process-global registry. Each `Param(...)` default becomes a pydantic field; bare defaults are rejected at decoration time.
- `eggseis.plugin_loader` — discovery from built-ins, `$EGGSEIS_PLUGIN_PATH` (os.pathsep-separated), `~/.eggseis/plugins/`, and `eggseis.plugins` entry points. `load_errors()` collects per-source failures so the GUI and CLI can surface them.
- `eggseis.plugin_runner.run_on_section` — synchronous fan-out across the visible section, scalar + vectorized paths, optional `context` dict (`sample_rate_ms`, `axis`, `index`).
- `eggseis.plugin_template` — generator backing **File → New Plugin…**: slugifies the name, writes a working starter, opens the file in the OS default editor.
- `eggseis.builtins.*` — Envelope, Instantaneous Phase, Instantaneous Frequency, RMS Amplitude, Ormsby Bandpass. Ormsby is hardened against short traces, slider crossover, and Nyquist-edge values.
- `eggseis.widgets.param_dock.ParamDock` — magicgui-built parameter editor docked right of the section viewer; bound numeric Params render as `FloatSlider` / `Slider` with auto-derived smooth steps.
- `SectionViewer` overlay paint + **View → Lock Levels to Raw** (default ON): overlays render against the raw-slice (1, 99) percentile range, so amplitude-changing plugins (gain, clip) are visibly intuitive instead of normalized away.
- `MainWindow`: `Attribute` menu populated from discovered plugins, `File → New Plugin…`, `Help → Plugin Errors…` with a startup status-bar hint.
- `eggseis plugins [--params] [--show-errors]` CLI subcommand.
- `docs/plugin-authoring.md` — authoring reference (parameter widget rules, decorator options, vectorized mode, troubleshooting, distribution via entry points). Cross-linked from `docs/development.md`.

### Changed
- `pyproject.toml` `gui` extra adds `pydantic>=2.7`, `magicgui>=0.9`, `scipy>=1.13`.
- `ROADMAP.md` renumbered: new **M5 (linear pipeline chain)** and **M6 (DAG + visual node-graph canvas)** inserted before horizons/wells/volume/crossplot. Schedule extends to ~61 weeks part-time. New design-decisions row covers plugin composition.
- `M2-PLAN.md` cross-references updated to new milestone numbers (project save → M7, volume viewer → M8, crossplot → M9).
- `docs/m2-screenshot.png` regenerated by the pre-commit hook to reflect the Parameters dock + Attribute menu.

### Notes
- Plugins are trace-local (Tier 1) only in M3 by design. Threading, debounce, cancellation, and the in-memory LRU cache land in M4. Pipeline chains land in M5; DAG + canvas in M6. Project-file persistence of the active plugin lands in M7.
- 94 tests at the M3 cut. CI matrix green across macOS / Ubuntu / Windows × Python 3.11 / 3.12.

## [0.1.0a2] — 2026-04-26

**M2 — "The section appears" complete.**

### Added
- `eggseis.app.MainWindow` — first Qt application, with File / View / Help menus.
- `eggseis.project.Project` + `SurveyEntry` — load a project directory from a `project.yaml` manifest.
- `eggseis.widgets.project_tree.ProjectTreeWidget` — tree of surveys / horizons / wells (horizons + wells stubs reserved for M5).
- `eggseis.viewers.section.SectionViewer` — pyqtgraph `ImageItem` view with 1–99 percentile stretch, axis-aware crosshair readout, and configurable colormap.
- `eggseis.widgets.slice_nav.SliceNavigator` — axis combo + bounded spinbox driving the section.
- `eggseis.colormaps` — gray, seismic, and dependency-free viridis LUTs.
- `eggseis.axes.Axis` (StrEnum) + `AXES` — canonical axis names; `SurveyGeometry` gains `inline_at`, `xline_at`, `time_at`, and `range_for`.
- `eggseis gui [project_dir]` CLI subcommand.
- Keyboard shortcuts: ←/→ step ±1, PgUp/PgDown step ±10, I/X/T jump axis.
- `examples/demo-project/` — a checked-in project pointing at the existing `demo.mdio` fixture.
- `scripts/test.sh` runner with `setup` / `lint` / `test` / `gui` / `nogui` / `demo` / `shot` / `ci` subcommands.
- `scripts/screenshot.py` regenerates `docs/m2-screenshot.png` from the demo project.
- `docs/development.md` covering local dev workflow, headless mechanics, and shortcuts.
- `tests/test_gui_smoke.py` — headless `pytest-qt` end-to-end smoke driving open-project → swap-slice → swap-colormap.

### Changed
- CI matrix runs every job under `QT_QPA_PLATFORM=offscreen` and installs the Linux Qt runtime apt deps.
- README status block reflects M1 + M2 complete; gains a section-viewer screenshot.

### Notes
- GUI dependencies (PySide6, pyqtgraph, pyyaml) live behind a `gui` extra; the dev extra pulls them in plus pytest-qt.
- Project save, threading / debounce, and plugin integration remain out of scope for v0.1 — they belong to M5, M4, and M3 respectively.

## [0.1.0a1] — 2026-04-26

**M1 — "The data opens" complete.**

### Added
- `eggseis.data.SeismicVolume` — stable public abstraction over a 3D seismic volume.
- `eggseis.data.SurveyGeometry` — frozen dataclass describing inline/xline/sample geometry.
- `eggseis.data.SeismicBackend` — `Protocol` defining the storage backend contract.
- `eggseis.backends.mdio.MDIOBackend` — first backend, reads MDIO v1 surveys.
- `eggseis.cli` — Typer-based CLI with `eggseis info` and `eggseis dump-inline` commands.
- Synthetic MDIO fixture in `tests/conftest.py` for deterministic backend tests.
- GitHub Actions CI matrix on Linux/macOS/Windows × Python 3.11 / 3.12 running `pytest` and `ruff`.

### Notes
- Pre-alpha. API is stable for the surface listed above; everything else is subject to change.
- Not published to PyPI.
