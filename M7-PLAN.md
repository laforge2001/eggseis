# M7 — "Horizons and wells"

**Milestone 7 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M6-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Import horizons + wells from the formats geologists actually have on disk, render them as overlays on the section viewer, and persist the project state — including M6's graph topology + params — so the user can close the app and reopen exactly where they left off.

This is the milestone where eggseis stops being a "DAG plugin platform with seismic" and starts being a partial replacement for commercial interpretation software. The first moment a user can do real work with it, however limited.

## Exit criteria

You're done with M7 when this is true:

- Import a horizon (OpendTect ASCII, IHS grid, or XYZ CSV) → see it overlaid on the section in real time as you scroll inlines.
- Import a deviated well with logs (LAS 2.0/3.0 + XYZ deviation) → see its path on intersecting sections plus log curves alongside the trace.
- Trace-header byte-locations editor: open a survey whose import got geometry wrong → fix the byte locations → re-derive geometry without re-importing the volume.
- Project save: write `project.yaml` capturing tree state, viewer state (axis, index, colormap, levels), loaded plugins, and **the active survey's graph topology + params** (M6's `Graph.to_dict` already round-trips; persistence is the new work).
- Project load: round-trip the above without surprises. Open → identical state. Includes loaded horizons + wells.
- M6 carry-overs landed: drop the orphaned `eggseis.pipeline` package, support multi-source graphs (cross-survey subtract), streaming volume export.
- Headless tests cover: horizon I/O round-trip, well I/O round-trip, section overlay rendering math, project save/load round-trip with a non-trivial graph, schema-version mismatch refusal.
- 282 tests at the M6 cut + roughly +50 new = ~330 at the M7 cut.
- CI matrix green across macOS / Ubuntu / Windows × Python 3.11 / 3.12.

---

## Step 0: Horizon storage spike — **DONE, sibling-store cleared**

Per the convention M5/M6 set: a short throwaway experiment to test the riskiest design assumption before plan-lock.

**Verdict: Option B (sibling store) wins.** ROADMAP suggested Option A (Zarr 2D array inside the survey container); spike evidence overrode that hint.

Spike at `examples/horizon_spike.py` confirmed both options round-trip cleanly:

- **Option A (side-var inside `<survey>.mdio`):** `xr.Dataset(...).to_zarr(path, mode="a")` writes a new variable; `open_mdio` reopens and surfaces it. Works.
- **Option B (sibling `<project>/horizons/<name>.zarr` + `<name>.json` sidecar):** `zarr.open(..., mode="w")` writes the array; sidecar JSON holds non-gridded attributes (unit, color, picker, geometry_ref). Works.

**Why B wins:**

- Survey directory stays canonical, read-only-friendly. Interpretation is user-owned and mutable.
- Re-import / overwrite of the survey doesn't silently nuke horizons.
- Multi-horizon projects get a natural directory grouping. Survey re-mount on read-only storage stays trivial.
- Matches the pattern every commercial platform uses (Petrel, OpendTect, Kingdom).
- Section viewer doesn't need to filter `data_vars` to separate seismic from overlay.
- Wells will follow the same shape (`<project>/wells/<name>.h5`), confirming the pattern scales.

**Caveats taken into the plan:**

- `Horizon` storage layout locked: one Zarr array `horizon` (2D, shape = `(n_inlines, n_xlines)`, dtype `float32`) + one sidecar JSON. Both inside `<project>/horizons/<name>/`.
- Sidecar attrs: `unit` (always `"ms"` in v1.0), `color`, `picker`, `geometry_ref` (relative path back to survey for shape verification on load).
- `project.yaml` gains `horizons: [{name, path, color}]` and `wells: [{name, path}]` lists. Empty defaults preserve M2/M5/M6 manifests.
- Zarr-3 consolidated-metadata warning fires on read; harmless, document.
- Path resolution helper required: `Project.resolve_horizon_path(name) -> Path` and `Project.resolve_well_path(name) -> Path`. Both relative to the project root.

Spike artefact stays in the tree as the simplest reproducer for any future regression.

## Step 1: Project schema versioning

Locking this first — every other M7 step writes to disk.

```yaml
schema_version: 1
name: "Project name"
surveys: [...]
horizons:                # new in v1
  - name: "Top reservoir"
    path: "horizons/top_reservoir"
    color: "#ffcc00"
wells:                   # new in v1
  - name: "Well-01"
    path: "wells/well_01.h5"
graph:                   # new in v1: M6 graph for the active survey
  active_survey: "demo"
  graph: { ... Graph.to_dict() ... }
viewer:                  # new in v1: viewport restoration
  axis: "inline"
  index: 110
  colormap: "seismic"
  levels_locked: true
```

**Locked decisions:**

- `schema_version: int` at top level. Single integer; not semver.
- Loader refuses to open `schema_version > KNOWN_VERSION`. Loader's behaviour for `schema_version < KNOWN_VERSION` is one-direction migration (`migrations.py` module of small functions per upgrade step).
- M2 manifests had no `schema_version`; treat missing field as version 0; bootstrap to version 1 on first save.
- Field additions to existing top-level keys are non-breaking and DON'T bump the version. Renames or removals DO.

## Step 2: Horizon I/O

```
src/eggseis/data/horizon.py     # Horizon dataclass + write/read
src/eggseis/io/horizon_import.py  # OpendTect ASCII / IHS grid / XYZ CSV importers
```

```python
@dataclass
class Horizon:
    name: str
    grid: np.ndarray          # (n_inlines, n_xlines) float32, ms
    geometry_ref: str         # relative path to source survey
    color: str = "#ffcc00"
    picker: str = ""

    @classmethod
    def load(cls, path: Path) -> "Horizon": ...
    def save(self, path: Path) -> None: ...
    def value_at(self, inline: int, xline: int) -> float | None: ...
```

Importers normalise to a `(n_inlines, n_xlines)` grid via the survey's `SurveyGeometry`. Mismatched geometries (horizon doesn't cover all inlines) write `np.nan` for missing samples; `value_at` returns `None` for nan.

**Importers, in order of priority:**
1. **XYZ CSV** — three-column inline / xline / time. Easiest to test, easiest to author by hand. Implement first.
2. **OpendTect ASCII** — header + columns. Most common in academic + open-source workflows.
3. **IHS grid** — binary, more involved. Defer to last.

## Step 3: Horizon overlay on the section viewer

```python
class HorizonOverlay:
    def __init__(self, horizon: Horizon, color: str): ...
    def update_for_slice(self, axis: Axis, index: int, geometry: SurveyGeometry) -> None:
        """Recompute polyline points for the new section."""
```

For an inline section at index `I`:
- Extract `horizon.grid[i_idx, :]` where `i_idx = I - geometry.inline_min`.
- Convert each (xline, depth_ms) point to image-space pixels via geometry helpers.
- Draw a `pyqtgraph.PlotDataItem` polyline.

For an xline section: extract `horizon.grid[:, x_idx]`. For timeslice: a contour at the slice depth (deferred to M7.5 or v1.1 — out of scope).

`SectionViewer.add_horizon_overlay(horizon, color)` and `.remove_horizon_overlay(name)` are the public surface. Multiple horizons render as multiple polylines.

## Step 4: Well I/O

```
src/eggseis/data/well.py            # Well dataclass + HDF5 read/write
src/eggseis/io/well_import.py       # LAS 2.0/3.0 + XYZ deviation importers
```

```python
@dataclass
class Well:
    name: str
    deviation: np.ndarray      # (n_md, 3) — md, x, y or md, dx, dy
    logs: dict[str, np.ndarray]  # log_name -> (n_md,) values
    markers: list[tuple[str, float]]  # (name, md)
    surface_xy: tuple[float, float]   # well-head in survey coords

    @classmethod
    def load(cls, path: Path) -> "Well": ...
    def save(self, path: Path) -> None: ...
    def intersect_section(self, axis: Axis, index: int, geometry: SurveyGeometry) -> np.ndarray:
        """Return (n_points, 2) array of (xline_or_inline, time) where the well crosses."""
```

LAS via `lasio` (already in the Python ecosystem; lightweight). XYZ deviation: simple CSV — md, x, y, optionally inline/xline.

`Well.intersect_section` returns the (xline-or-inline, time) coordinates where the deviated path passes through the section plane. Tolerance: a configurable `slice_thickness` (default 1 inline / xline) — anything within the slab gets drawn.

**Step 4 risks:** LAS files in the wild are messy. Spike on 5–10 real files (synthetic + a couple from public sources) before plan-locking the importer details. Surface a clear `LasImportError` for malformed input rather than crashing.

## Step 5: Well overlay on the section viewer

For each well: deviated path drawn as a polyline; log curves rendered as small per-trace plots alongside the section (configurable lane on the right or left).

`SectionViewer.add_well_overlay(well, *, log_name=None)`. Without a log, just the path. With a log, add a side panel.

Multiple wells render as multiple polylines + multiple log lanes.

## Step 6: Header editor

```
src/eggseis/widgets/header_editor.py
```

Modeless `QDialog` opened via `Survey → Edit Trace Headers…` menu. Lists current byte-location bindings (inline at byte 189, xline at byte 193, etc.); user edits; `Apply` re-derives `SurveyGeometry` from the new bindings without re-reading the volume.

Out of scope for M7: writing back a corrected MDIO. Edit is in-memory only; affects this session.

## Step 7: Project save / load

```python
class Project:
    schema_version: int = 1

    def save(self, path: Path | None = None) -> None:
        """Write project.yaml with schema_version + all currently-loaded state."""
    @classmethod
    def load(cls, path: Path) -> "Project":
        """Refuse if schema_version > KNOWN_VERSION; migrate older versions."""
```

`MainWindow` calls `Project.save` from `File → Save Project` and on app quit (with a "save before quit?" prompt if dirty).

The serialised graph uses M6's `Graph.to_dict` directly — no new code. Loader needs the plugin registry to reconstruct: any orphan plugin (loaded survey was using a plugin that's not registered now) fails with `OrphanPluginError` per M6 contract. Surface in a dialog: "Plugin X not available; do you want to skip / install / abort?".

## Step 8: M6 carry-overs

### 8a — Drop M5 `eggseis.pipeline` package

Scheduled remote agent fires 2026-05-14 to verify orphan status + open the deletion PR. If the agent runs before M7 starts in earnest, land that PR first to keep diff sizes manageable.

### 8b — Multi-source graphs (cross-survey subtract)

The natural seam M7 introduces: Source becomes a `kind` instead of a singleton. Per-survey Source instances; `Graph` carries a `volumes: dict[survey_id, SeismicVolume]` map; `GraphExecutor` reads from the right volume per Source-rooted edge; cache key folds in each contributing volume's `volume_version`.

Shape-match constraint: cross-survey subtract requires inline/xline/sample compatibility. Add a runtime shape check with a clear error.

UI: drag a survey from the project tree onto the canvas to spawn its Source node. Or right-click → "Add Source from open survey".

### 8c — Streaming volume export

Replace the in-memory cube in `export_volume_with_graph` with chunked zarr writes: create the empty zarr store with the target shape + chunks, then write each computed inline directly into its chunk via `xr.Dataset.to_zarr(region=...)`. Removes the 8 GB cap.

## Step 9: Tests

Roughly 50 new tests across:

- `test_horizon_io.py` — round-trip Horizon save/load, importers (XYZ, OpendTect, IHS), missing-data NaN handling.
- `test_horizon_overlay.py` — polyline math for inline / xline; nan sample is skipped; multi-horizon rendering.
- `test_well_io.py` — LAS round-trip, deviation import, malformed-file error path, multi-log file.
- `test_well_overlay.py` — `intersect_section` math; deeply curved well crossing many sections at 60 fps under slider drag (perf smoke).
- `test_project_save_load.py` — round-trip with a non-trivial graph + horizons + wells; schema_version refusal of v0; migration from v0 to v1.
- `test_multi_source.py` — cross-survey subtract works; mismatched geometry raises.
- `test_streaming_export.py` — replaces M6's in-memory test for surveys >8 GB (use a synthetic giant geometry, write zero-cost dummy data).

## Step 10: CLI / docs

- New CLI commands: `eggseis horizon import <project> <name> <file>`, `eggseis well import <project> <name> <file>`. Both write into the project directly.
- `docs/development.md` gains a "How project save / load works" section.
- `docs/plugin-authoring.md` gains a multi-source graph note (when 8b lands).
- README status row: `M7: horizons + wells — overlays, project persistence, multi-source graphs.`
- CHANGELOG `[v0.1.0a7]` entry.

## Step 11: Status surface

- `Help → Project Errors…` (new): aggregates schema-version warnings, missing-plugin errors, malformed-import errors. Same shape as M3's `Help → Plugin Errors…`.
- Status bar shows "Loading horizon…" / "Loading well…" / "Saving project…" with progress where applicable.

---

## Locked design decisions for M7

| Area | Decision |
|---|---|
| Horizon storage | Sibling Zarr store under `<project>/horizons/<name>/` + JSON sidecar. ROADMAP's "inside survey container" hint overridden by Step 0 spike. |
| Well storage | HDF5 file under `<project>/wells/<name>.h5`. Same separation principle as horizons. |
| Schema versioning | Single integer `schema_version` at top of `project.yaml`. Loader refuses unknown future versions; one-direction migration for older versions. |
| Horizon overlay | pyqtgraph `PlotDataItem` polyline per horizon. Multi-horizon = multiple items. Configurable per-horizon color. |
| Well overlay | pyqtgraph polyline for the path; per-log side-panel lane (configurable left/right). |
| Header editor | In-memory geometry override only; doesn't write back to MDIO. |
| Project graph persistence | M6's `Graph.to_dict` direct serialisation. Per-active-survey only in v1; multi-graph projects deferred. |
| Multi-source graphs | Source becomes a `kind`; per-survey Source nodes; shape-match enforced at execution. UI: drag survey from tree onto canvas. |
| Streaming export | Chunked `to_zarr(region=...)` writes per inline. Removes the 8 GB in-memory cap. |
| LAS dependency | `lasio` (added to `gui` extra). |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Project                                            │
│   ├── schema_version: 1                             │
│   ├── surveys: [...]                                │
│   ├── horizons: [...]   ─── eggseis.data.Horizon   │
│   ├── wells: [...]      ─── eggseis.data.Well      │
│   ├── graph: {to_dict}  ─── eggseis.graph.Graph    │
│   └── viewer: {axis, index, colormap, levels}      │
└─────────────────┬───────────────────────────────────┘
                  │ Project.save / Project.load
                  ▼
        <project_dir>/
          project.yaml
          horizons/<name>/
            horizon (zarr 2D)
            sidecar.json
          wells/<name>.h5
          surveys/<name>.mdio        # M2-M6 unchanged
```

`MainWindow` gains `_horizons: dict[name, Horizon]` and `_wells: dict[name, Well]` per active survey. Section viewer iterates the loaded set on every slice change.

---

## Execution order

0. **Horizon storage spike — DONE.** (Step 0 above.)
1. Lock schema versioning (Step 1). Add `Project.schema_version`, refusal logic, empty migrations module. Tests for refusal + identity-migration.
2. Horizon I/O (Step 2). Save/load round-trip, XYZ CSV importer first.
3. Horizon overlay (Step 3). Single-inline polyline, then xline, then multi-horizon.
4. Project save/load with horizons + graph (Step 7 partial — graph persistence). Tests round-tripping a non-trivial graph.
5. OpendTect ASCII + IHS grid horizon importers (finish Step 2).
6. Well I/O (Step 4) + LAS spike on real files.
7. Well overlay (Step 5).
8. Header editor (Step 6).
9. M6 carry-over 8a (drop pipeline package). Coordinate with the scheduled agent.
10. M6 carry-over 8b (multi-source graphs). Bigger refactor; sequence after horizons land so the data-type plumbing is already in place.
11. M6 carry-over 8c (streaming export).
12. CLI + docs + CHANGELOG (Steps 10).
13. `./scripts/test.sh ci` green on the CI matrix.

ROADMAP weeks 30–35 (~6 weeks part-time). Likely time-sinks: LAS edge cases (Step 6), multi-source graph executor refactor (Step 10), and project-load orphan-plugin recovery dialog (Step 7).

---

## Risks

- **Real LAS files break the importer.** Files in the wild are messy. Mitigation: Step 6 spike on 5–10 representative files before locking importer behaviour. Surface `LasImportError` clearly; never crash on malformed input.
- **Schema-versioning lock is irreversible-ish.** Once v1 manifests are written, breaking changes require a migration step. Lock the field shapes carefully in Step 1; resist scope creep.
- **Project graph persistence + plugin-registry coupling.** A loaded project might reference plugins that aren't registered in the current session (deleted plugin file, fresh checkout, different machine). Need a clear recovery flow — orphan-plugin error dialog with skip/install/abort. M6 already raises `OrphanPluginError`; M7 surfaces it.
- **Multi-source executor refactor depth.** Section 8b touches `Graph` (Source becomes a kind), `GraphExecutor` (multi-volume reads), `port_hash` (per-Source `volume_version`), canvas (drag-survey-onto-canvas UI), and the cache. ~2-3 days alone; sequence after horizons so other work can land while this is in progress.
- **Streaming export atomicity.** Cancelling a chunked write mid-export leaves a half-written zarr store. Need a `.tmp` write + atomic rename pattern, or document that cancellation deletes the partial output.
- **Header editor scope creep.** Resist writing-back-to-MDIO. Edit is in-memory only; persisting a corrected MDIO is a v1.1 feature.
- **Well-log render perf.** Deeply curved well crossing many sections, each with a log lane, under slider drag. May need datashader or downsampling. Spike on a real well during Step 5 if performance flags.

---

## Out of scope for M7

- Manual horizon picking (interactive picking on the section viewer). Out of scope for v1.0 entirely (M11+).
- Horizon auto-tracking. v2.0.
- Well log editing. v2.0.
- Time-domain conversion (depth ↔ time). Future milestone.
- Volume rendering (M8).
- Crossplot (M9).
- Multi-graph-per-project (M7 ships one active graph per project).

---

## When M7 is done

A clean exit looks like:

- Open a project, see surveys + horizons + wells in the tree. Double-click a survey, see horizons overlaid on the section as you scroll inlines.
- Build a 3-node graph on the active survey, save the project, close the app, reopen — graph + horizons + wells all back exactly as they were.
- Cross-survey subtract works: load survey A and survey B in the same project, drag both Source nodes onto the canvas, wire into a `subtract`, see the difference.
- Volume export streams to disk for surveys larger than 8 GB.
- The M5 pipeline package is gone.
- README and `docs/development.md` updated. CHANGELOG entry under `[v0.1.0a7]`.
- Tag `v0.1.0a7` after the M7 PR merges.
- Take a beat. Then start M8 — "The volume" (PyVista volume viewer + linked cursor with section viewer).
