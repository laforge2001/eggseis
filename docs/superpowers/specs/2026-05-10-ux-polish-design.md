# UX Polish Milestone — PaleoScan-Aligned Theme Pass

**Status:** Design — pending plan
**Tracking issue:** #19
**Predecessor:** v0.1.0a7 (M7: horizons + wells)
**Successor:** M8 (volume viewer, deferred until this lands)

## Goal

Bring the GUI to a polish level that holds up against PaleoScan / Petrel / OpendTect on first demo. Audience is geoscientists; janky-looking chrome loses them before they engage with the substance. This milestone is "comprehensive but bounded" — STANDARD envelope (~2 weeks, 4-5 PRs), not a never-ending visual overhaul.

## Non-goals

- Live theme switching tied to OS palette change events (defer to v1.1).
- Per-user persistent theme overrides outside of `project.yaml`.
- Custom hand-drawn icon set replacing QtAwesome — defer to v1.1 if needed.
- Smooth dock open/close animations and splash screen — Qt-fragile, defer.
- Comprehensive section viewer reticle / scale bar — defer.

## Architecture

### Module layout

```
src/eggseis/
  style/                              NEW
    __init__.py                         apply_theme, current_mode, Theme enum, themeChanged signal
    qss/dark_overrides.qss              accent + splitter + status bar tweaks (dark)
    qss/light_overrides.qss             same tokens, light values
  viewers/
    theme.py                            EXTENDED — accent, surface, border, text_muted tokens
    colormaps.py                        NEW — get_cmap, DEFAULT_AMPLITUDE, DEFAULT_ATTRIBUTE
    section.py                          MODIFIED — colorbar widget + per-output cmap
  widgets/
    welcome.py                          NEW — empty-state widget shown when no project
    status_bar.py                       NEW — segmented status bar
    toolbar.py                          NEW — primary toolbar with QtAwesome icons
    tree_icons.py                       NEW — QtAwesome icons on category roots
  app.py                                MODIFIED — wires welcome, toolbar, status bar, theme
  plugin.py                             MODIFIED — Param decorator gains optional `cmap=`
  resources/
    eggseis.svg                         NEW — app icon
    eggseis.icns                        NEW — macOS packaging
    eggseis.ico                         NEW — Windows packaging
  gallery.py                            NEW — `python -m eggseis.gallery` for visual regression
scripts/
  build_app_icon.sh                     NEW — converts SVG → ICNS/ICO (maintainer-run)
```

### Dependencies

All gated behind the existing `[gui]` extra in `pyproject.toml`:

- `pyqtdarktheme` (~150 KB pure-Python) — base dark/light Qt palette + stylesheet
- `qtawesome` (~600 KB, FontAwesome + Material font files) — toolbar/tree icons
- `cmcrameri` (~50 KB) — perceptually uniform colormaps (vik, batlow, etc.)

### Theme propagation

`app.py` calls `style.apply_theme(Theme.DARK)` on startup. Order:

1. `qdarktheme.setup_theme("dark")` installs Qt palette and base stylesheet.
2. Override QSS loaded from `style/qss/dark_overrides.qss`, tokens substituted via Python f-string against `viewers.theme.colors()`.
3. Combined stylesheet applied via `QApplication.setStyleSheet(base + overrides)`.
4. `style.themeChanged` signal emitted.
5. Each viewer (SectionViewer, MapViewWidget, GraphCanvas, WellLogPanel) connects to `themeChanged` on construction and calls its own `_reapply_theme()` to refresh pyqtgraph pens, colorbar text, qtpynodeeditor scene colors.

The active mode persists in `project.yaml` under `viewer.theme: dark|light`. On `open_project`, `_restore_viewer_state` re-applies the saved mode. Default for fresh installs is `dark`.

## Components

### `style.apply_theme(mode: Theme)`

```python
class Theme(StrEnum):
    DARK = "dark"
    LIGHT = "light"

class _ThemeSignals(QObject):
    themeChanged = Signal(Theme)

theme_signals = _ThemeSignals()  # module-level singleton; viewers connect to theme_signals.themeChanged

def apply_theme(mode: Theme) -> None: ...
def current_mode() -> Theme: ...
```

Idempotent: calling `apply_theme(DARK)` twice in a row is a no-op (no extra signal emission). Failure to load override.qss logs a warning and continues with pyqtdarktheme base only. The `theme_signals` singleton is the canonical Qt host for the cross-module signal — viewers import and connect: `from eggseis.style import theme_signals; theme_signals.themeChanged.connect(self._reapply_theme)`.

### `viewers/colormaps.py`

```python
DEFAULT_AMPLITUDE = "cmcrameri:vik"     # diverging, perceptually uniform
DEFAULT_ATTRIBUTE = "cmcrameri:batlow"  # uniform, colorblind-safe

def get_cmap(name: str) -> pg.ColorMap: ...
def available() -> list[str]: ...       # for dropdown population
```

Resolves `cmcrameri:vik`, `mpl:viridis`, etc. Returns a pyqtgraph ColorMap sampled to 256 stops via numpy. Unknown name raises `KeyError` at the boundary; callers fall back to defaults. If `cmcrameri` is not installed, falls back to matplotlib equivalents (`vik` → `RdBu_r`, `batlow` → `viridis`).

### `plugin.Param(... cmap=None)`

Optional keyword on the `@plugin` decorator metadata:

```python
@plugin(name="envelope", cmap="cmcrameri:batlow")
def envelope(section, ...): ...
```

Plugin registry stores `cmap` alongside `params`. Validated at decoration time; bad cmap name raises `PluginRegistrationError`. Section viewer reads `node.plugin.cmap` for plugin outputs (fallback `DEFAULT_ATTRIBUTE`); raw Source uses `DEFAULT_AMPLITUDE`.

### `widgets/welcome.py`

```python
class WelcomeWidget(QWidget):
    openProjectRequested = Signal()
    newProjectRequested = Signal()
    recentRequested = Signal(str)  # absolute path
```

Shown as `MainWindow.centralWidget()` when `self._project is None`. Layout: app glyph (large), tagline, two primary buttons (Open Project ⌘O, New Project), recent projects list (up to 5 entries from `~/.eggseis/recent.json`).

### `widgets/toolbar.py`

```python
class PrimaryToolbar(QToolBar):
    def __init__(self, actions: ToolbarActions): ...
    def set_project_loaded(self, loaded: bool) -> None: ...
```

Eight buttons in three groups: `[open, save] | [import survey, import horizon, import well] | [add plugin, export volume]`. Each button references an existing `QAction` from MainWindow (no duplicate handlers). `set_project_loaded(False)` greys out import / plugin / export buttons; open and save remain enabled.

### `widgets/status_bar.py`

```python
class SegmentedStatusBar(QStatusBar):
    def set_project_name(self, name: str | None) -> None: ...
    def set_cursor(self, inline: int | None, xline: int | None, t_ms: float | None) -> None: ...
    def set_cache_rate(self, pct: float) -> None: ...
```

Segments shown left-to-right via `addPermanentWidget`: project label · cursor coords · cache hit-rate · version. Version is static. Project name updates on `open_project` / close. Cursor updates from `SectionViewer.cursorMoved`. Cache rate from a new `ComputeOrchestrator.cacheRateChanged` signal (uses existing internal hit/miss counters).

### `widgets/tree_icons.py`

```python
def apply_to_tree(tree: ProjectTree) -> None: ...
```

Walks the tree's category roots and assigns QtAwesome icons:

- `Surveys` → `fa5s.th`
- `Horizons` → `fa5s.chart-area`
- `Wells` → `fa5s.tint` (water droplet — closest standard icon to a well)

Per-item children get no icons (PaleoScan-aligned low chrome).

### `viewers/section.py` modifications

- New `_colorbar: pg.ColorBarItem` linked to the image item, positioned to the right of the plot area.
- New `set_colormap(name: str)` — uses `colormaps.get_cmap`, updates image LUT and colorbar gradient.
- New colorbar header label shows the active cmap name (`"vik"`, `"batlow"`, etc.).
- Connects to `style.themeChanged` to refresh colorbar text colors.
- Plugin output path: reads `node.plugin.cmap` from graph metadata; fallback `DEFAULT_ATTRIBUTE`.
- Raw Source path: uses `DEFAULT_AMPLITUDE`.
- Per-section overrides stored in `project.yaml` under `viewer.section_cmap_overrides: dict[node_id, name]`.

### `gallery.py`

```bash
python -m eggseis.gallery --out docs/gallery/
```

Instantiates each themed widget against fake fixtures and screenshots to PNG. Catalog (12 PNGs):

- `welcome.png`, `main_loaded.png`
- `section_vik.png`, `section_batlow.png`, `section_gray.png`
- `map_view.png`, `canvas.png`, `log_panel.png`, `header_editor.png`
- `theme_dark.png`, `theme_light.png`
- `m2-screenshot.png` (the existing canonical screenshot, regenerated)

Output committed to `docs/gallery/`. Used for visual regression review on the PR (eye-diff, no pixel-exact assertion). CI smoke (`test_gallery.py`) runs the entry point against fake data and asserts each PNG is generated + non-empty.

### Resources / app icon

`src/eggseis/resources/eggseis.svg` — hand-tuned mark, an oval (egg) crossed by two seismic waveform peaks. Colors derive from the accent palette so it works on dark and light backgrounds. `scripts/build_app_icon.sh` invokes `iconutil` (macOS) and `magick` (cross-platform) to produce `.icns` and `.ico` from the SVG; outputs committed alongside the SVG. Maintainer runs this once when the SVG changes.

Packaging: `pyproject.toml` adds `[tool.setuptools.package-data] "eggseis.resources" = ["*.svg", "*.icns", "*.ico"]` so the icons are included in wheels and editable installs. App icon loaded via `QApplication.setWindowIcon(QIcon(importlib.resources.files("eggseis.resources") / "eggseis.svg"))`.

## Data Flow

### Theme tokens

Single source of truth: `viewers.theme.colors()` returns the active palette dict. New tokens added beyond M7's set:

- `accent` (`#2566c8` / `#5c9eff` light/dark) — buttons, highlights, selection
- `accent_muted` — disabled state of accent
- `surface` — panel backgrounds (slightly lighter than `background`)
- `surface_alt` — toolbar / status bar background
- `border` — splitter handles, panel borders
- `text_muted` — secondary text (status segments, tooltips)

Override.qss reads these tokens via Python f-string substitution before `setStyleSheet()`. Inline ternaries (`is_dark_mode() ? a : b`) are removed from all viewers; `colors()` is the only API.

### Plugin cmap declaration

```python
@plugin(name="envelope", cmap="cmcrameri:batlow")
def envelope(section, ...): ...
```

Stored in `_REGISTRY[name].cmap`. Read by section viewer's existing `_apply_plugin_output` pipeline. User-side override via the section colorbar's cmap dropdown is stored in `project.viewer.section_cmap_overrides[node_id]` and persists across save/load.

### Recent projects

- File: `~/.eggseis/recent.json` — list of `{path: str, timestamp: float}`, newest first, capped at 5.
- Updated on every `open_project` success (move to front, dedupe, truncate).
- `WelcomeWidget._load_recent()` reads on construction. Click emits `recentRequested(path)` → `MainWindow.open_project(path)`.
- Path no longer found at click time → don't silently drop; show "Project no longer found at <path>" in status bar so user knows.

### Status bar wiring

- Cursor coords: existing `SectionViewer.cursorMoved(inline, xline, t_ms)` → `status_bar.set_cursor`.
- Cache rate: new `ComputeOrchestrator.cacheRateChanged(pct: float)` signal emitted from worker pool callback (uses internal hit/miss counters already tracked in M4).
- Project name: set on `open_project` / `new_project`, cleared on close.

## Error Handling

- `qdarktheme.setup_theme()` raises on bad mode → caught in `style.apply_theme`, logs warning, falls back to current mode. Never crashes UI.
- Override.qss missing or malformed → logged warning, skipped (pyqtdarktheme base alone still works). Tested with deliberate corrupt QSS.
- `get_cmap("invalid:name")` → `KeyError` at the boundary; section viewer catches and falls back to defaults, emits one-time status bar warning.
- `cmcrameri` not installed (slim install) → `colormaps.py` detects on import, substitutes matplotlib equivalents.
- `~/.eggseis/recent.json` missing → empty list. Malformed JSON → logged warning, treated as empty, rewritten on next open.
- Recent project path no longer exists → still shown but greyed; click triggers "no longer found" message (not a silent drop).
- Plugin declares unknown `cmap=` → caught at decoration time, raises `PluginRegistrationError`.
- Plugin omits `cmap` → falls back to `DEFAULT_ATTRIBUTE`. No error.
- App icon `eggseis.svg` missing from package data → logged warning, no icon set. App launches normally.
- Toolbar buttons disabled while `project is None` via `QAction.setEnabled(False)` — handlers never trigger when disabled.

Boundary validation only: trust internal code (theme tokens, plugin registry); validate at user-input boundaries (cmap names from `project.yaml`, paths from disk).

## Testing

### Unit / integration

- `test_style.py` — `apply_theme(DARK|LIGHT)` sets stylesheet on QApplication; `themeChanged` fires once per change; double-apply is idempotent; bad mode raises and falls back.
- `test_colormaps.py` — `get_cmap` resolves `cmcrameri:*` and `mpl:*` names; unknown name raises `KeyError`; cmcrameri-missing fallback substitutes correctly.
- `test_welcome.py` — recent projects load from a tempdir-scoped fake home; `openProjectRequested`, `newProjectRequested`, `recentRequested(path)` emit on the right buttons; missing recent file → empty list.
- `test_status_bar.py` — segment setters update labels correctly; `set_cursor(None, None, None)` clears.
- `test_toolbar.py` — buttons disabled when project is None; enabled on `set_project_loaded(True)`; each button triggers the same `QAction` as the equivalent menu item.
- `test_tree_icons.py` — `apply_to_tree(tree)` sets icons on category roots only; per-item children get no icons.
- `test_plugin_cmap.py` — `@plugin(cmap="cmcrameri:batlow")` round-trips through registry metadata; bad cmap raises `PluginRegistrationError` at decoration time.
- `test_section_colorbar.py` — `set_colormap(name)` updates colorbar gradient + labels; `themeChanged` reapplies text colors; raw Source path uses `DEFAULT_AMPLITUDE`, plugin path uses plugin's `cmap` or `DEFAULT_ATTRIBUTE`.
- `test_recent_projects.py` — `open_project` appends + dedupes + caps at 5; non-existent path triggers "no longer found" status message.
- `test_gallery.py` — `python -m eggseis.gallery --out <tmp>` runs against fake data, asserts each PNG is generated and non-empty.

### Visual regression

`docs/gallery/` PNGs committed and reviewed by eye on the PR. No pixel-exact assertion (cross-OS unstable). Regenerate with `python -m eggseis.gallery --out docs/gallery/` whenever a visual surface changes.

`docs/m2-screenshot.png` regenerated as part of the gallery; pre-commit hook continues to auto-stage it on UI source changes.

### Coverage target

≥90% line coverage on new modules. Existing modules' coverage maintained.

### Out of scope for tests

- App icon load (Qt-internal, OS-specific).
- pyqtdarktheme internals.
- QSS stylesheet correctness (parser quirks; rely on visual gallery + manual PR review).

## Folded-in cleanup

Two pre-existing issues land naturally during this pass:

- **#17 stringly-typed Axis at signal boundaries** — the new `viewers.theme.colors()`-only convention removes inline ternaries; while we are touching every viewer's theme code we change `Signal(str, int)` to `Signal(Axis, int)` at `MapViewWidget.sliceRequested` and propagate `Axis` through `slice_nav.set_axis_and_index`. Receiving handlers in `MainWindow` already do `Axis(value)` casts; remove those.
- **#18 `SectionViewer.set_volume` overlay clear** — while modifying `section.py` for the colorbar, add the missing `_well_overlays` and `_horizon_overlays` clears on volume swap (mirrors `MapViewWidget.set_volume`'s pattern).

## Exit criteria

- App launches into the dark themed welcome screen with recent projects.
- View → Theme toggles between dark and light; selection persists in `project.yaml`.
- Primary toolbar with QtAwesome icons in MainWindow; buttons enabled/disabled with project state.
- Tree category roots show QtAwesome icons; per-item children do not.
- Section viewer shows a colorbar with the active cmap name; raw amplitude defaults to `cmcrameri:vik`; plugin outputs default to `cmcrameri:batlow` (or per-plugin `cmap=` declaration).
- Status bar shows project · cursor coords · cache hit-rate · version segments.
- App icon set on macOS dock (verify via `./scripts/test.sh demo`).
- `python -m eggseis.gallery --out docs/gallery/` produces 12 PNGs; CI smoke test asserts presence + non-empty.
- README screenshot regenerated and updated.
- `./scripts/test.sh ci` green.
- #17 (Axis at signal boundaries) and #18 (SectionViewer overlay clear) closed.

## CHANGELOG

`CHANGELOG.md` gets a `[0.1.0a8]` section dated on merge with sub-headings: Added (theme system, welcome screen, toolbar, status segments, colormaps, app icon, gallery), Changed (axis signals strongly typed), Fixed (section overlay clear on volume swap).

## Tagging

After merge: `git tag v0.1.0a8 main && git push origin v0.1.0a8`.
