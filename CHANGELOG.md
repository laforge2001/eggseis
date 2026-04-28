# Changelog

All notable changes to eggseis are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [PEP 440](https://peps.python.org/pep-0440/).

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
