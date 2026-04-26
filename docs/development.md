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
