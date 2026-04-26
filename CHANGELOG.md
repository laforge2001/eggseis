# Changelog

All notable changes to eggseis are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [PEP 440](https://peps.python.org/pep-0440/).

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
