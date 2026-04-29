# Development

Local dev workflow for eggseis. The repo ships a single entry point — `scripts/test.sh` — that wraps install, lint, and tests. Everything below assumes you're at the repo root.

## Prerequisites

- Python 3.11 or 3.12 (3.11 is the project floor).
- A virtual environment. The script auto-activates `.venv/` if it exists; create one if you don't have it:

  ```bash
  python -m venv .venv
  source .venv/bin/activate
  ```

  Conda also works (`conda create -n eggseis python=3.12 && conda activate eggseis`).

## First-time setup

Install the package in editable mode with all dev extras:

```bash
./scripts/test.sh setup
```

That runs `pip install -e ".[dev]"`, which pulls in:

- The library itself (numpy, mdio, typer, rich, pillow).
- The `gui` extra (PySide6, pyqtgraph, pyyaml).
- Test tooling (pytest, pytest-qt, ruff, mypy, pytest-cov).

PySide6 is a ~500 MB download — first install is slow.

**Recommended:** also enable the project's git hooks so the section-viewer screenshot in `docs/m2-screenshot.png` regenerates automatically whenever you commit a change to UI sources, the demo project, or the screenshot script:

```bash
./scripts/test.sh hooks
```

That just runs `git config core.hooksPath .githooks`. The hook skips silently if PySide6 isn't installed, so it never blocks a library-only checkout.

## Running tests

| Command | What it runs |
|---|---|
| `./scripts/test.sh` | Full pytest suite, headless. Default. |
| `./scripts/test.sh test` | Same as above. |
| `./scripts/test.sh gui` | Only the GUI smoke test, headless. |
| `./scripts/test.sh nogui` | Everything except the GUI smoke test. |
| `./scripts/test.sh lint` | `ruff check .` |
| `./scripts/test.sh ci` | Lint + full headless suite. Mirrors GitHub Actions. |
| `./scripts/test.sh shot` | Regenerate `docs/m2-screenshot.png` from the demo project. |
| `./scripts/test.sh hooks` | Point git at `.githooks/` so the screenshot auto-regenerates on UI commits. |

Anything after the command forwards to pytest:

```bash
./scripts/test.sh test -k colormaps -v
./scripts/test.sh gui --tb=short
./scripts/test.sh nogui -x
```

A clean run looks like `27 passed`.

### Headless under the hood

The `test`, `gui`, and `ci` subcommands set `QT_QPA_PLATFORM=offscreen` so PySide6 never tries to open a real window. That's how CI runs on Linux/macOS/Windows runners without a display server. You can replicate the CI invocation manually:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

## Seeing the GUI

The smoke tests assert state and exit — they never display a window even on a real desktop. To actually run the app:

```bash
./scripts/test.sh demo
```

That launches `eggseis gui examples/demo-project/`, which loads the synthetic `demo.mdio` checked into the repo. Double-click the survey under "Surveys", then use View → Colormap to swap LUTs.

To open a different project:

```bash
eggseis gui /path/to/your/project/
```

A project is any directory containing a `project.yaml` manifest — see `examples/demo-project/project.yaml` for the minimum schema.

### Keyboard shortcuts

| Key | Action |
|---|---|
| ← / → | Step the current slice by one |
| PgUp / PgDown | Step the current slice by ten |
| I / X / T | Switch axis to inline / xline / timeslice |

### Plugins (M3)

Trace-local attributes register via `@trace_attribute` and appear in the
**Attribute** menu. The `Parameters` dock auto-builds sliders from each
`Param(...)` declaration. See **`docs/plugin-authoring.md`** for the full
reference, parameter widget rules, examples, and troubleshooting.

Quick checks:

```bash
eggseis plugins              # list discovered plugins + their source paths
eggseis plugins --params     # also show parameter declarations
```

Discovery sources, in order: built-ins → `$EGGSEIS_PLUGIN_PATH` (os.pathsep-
separated) → `~/.eggseis/plugins/` → installed `eggseis.plugins` entry points.
**File → New Plugin…** in the GUI writes a starter file under
`~/.eggseis/plugins/` and opens it in your editor.

## Continuous integration

Every push to a PR runs `.github/workflows/tests.yml` across:

- ubuntu-latest, macos-latest, windows-latest
- Python 3.11 and 3.12

CI installs the Linux Qt runtime apt deps (`libegl1`, `libxkbcommon0`, `libdbus-1-3`, `libxcb-cursor0`) before `pip install -e ".[dev]"`. Local Linux runs may need the same packages if PySide6 import fails.

## Editing conventions

- **No `time.sleep` in Qt tests** — use `qtbot.waitSignal` or `qtbot.waitUntil`.
- **No pixel-exact image asserts** cross-OS — font rendering differs on Linux vs macOS.
- **Run `./scripts/test.sh ci` before opening a PR** — that's exactly what GitHub Actions runs.

## Troubleshooting

**PySide6 import error on Linux** — install the runtime libs:

```bash
sudo apt-get install -y libegl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0
```

**`numcodecs.zarr3` deprecation warning** — comes from inside `mdio`. Harmless, will go away when mdio bumps its zarr usage.

**`QApplication` fails on macOS** — make sure you're not running tests inside another QApplication (e.g. an IDE plugin). pytest-qt's `qapp` fixture already handles this in tests; outside tests, instantiate `QApplication.instance() or QApplication(sys.argv)`.

**`./scripts/test.sh demo` shows an empty viewer** — double-click the survey under the "Surveys" branch in the project tree. Single-click only selects it.

## Compute model (M4+)

When you select an attribute in the GUI, the section is computed off the GUI
thread by `eggseis.compute.JobOrchestrator`:

1. `MainWindow._recompute_overlay` calls `orchestrator.request(...)`.
2. The request is debounced 150 ms; rapid slider chatter coalesces into one
   dispatch.
3. On dispatch the orchestrator splits the section into 64-trace tiles and
   submits one `TileRunnable` per tile to `QThreadPool.globalInstance()`.
   Tiles are ordered center-out so the visible middle of the section appears
   first.
4. As tiles complete, the orchestrator coalesces them into a `tilesReady`
   emission every 50 ms; the section viewer paints partial results.
5. When the last tile lands, `sectionReady` fires and the result is stored
   in `SectionLRU` (default 500 MB, override with `EGGSEIS_CACHE_BYTES`).
6. Identical subsequent requests serve from cache and return synchronously
   without ever touching a worker.

Library/CLI paths (`eggseis info`, `eggseis dump-inline`,
`eggseis.plugin_runner.run_on_section`) stay synchronous — the orchestrator
is GUI-only.

## How pipelines work in the GUI (M5+)

eggseis lets the user stack multiple trace-local plugins into a linear
pipeline per survey. The dock at the left of the main window lists the
chain; each node has an enable checkbox and a tap radio. The section
viewer paints the output of whichever node is tapped (Source = raw
amplitude).

Mechanics:

- **Per-survey scope.** Each opened survey gets its own `Pipeline`,
  kept in memory for the session. Closing a survey doesn't lose the
  chain; opening a different survey shows that survey's chain (which
  may be empty). Persistence to disk is M7's job.

- **Cache via `chain_hash`.** Each node has a content-addressed key
  that folds in `(plugin_id, plugin_version, params, parent_chain_hash)`.
  The M4 `SectionLRU` is reused directly — there is no separate
  pipeline cache. Editing one node's params leaves all upstream cache
  entries intact; downstream entries miss naturally because their
  `chain_hash` differs.

- **Lazy recompute.** Only the path from Source to the current tap
  runs. If you tap node 1, nodes 2–5 stay dirty until you tap one of
  them; then the cold suffix runs.

- **Disabled nodes** are skipped at execution time (they pass their
  parent's output through unchanged) and their tap radio is greyed.
  The cache key reflects the skip, so disabling a node does not
  invalidate cached entries for an upstream node — only downstream
  nodes re-key.

- **Non-deterministic plugins** (`deterministic=False`) and every
  node downstream of one are excluded from cache reads and writes.
  The plugin itself runs normally; results are simply not memoised.

- **Timeslice axis** bypasses the chain entirely. Trace-local plugins
  do not apply to a horizontal slice; the viewer paints raw amplitude
  until the user switches to inline or xline.
