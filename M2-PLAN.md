# M2 — "The section appears"

**Milestone 2 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M1-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Build the first Qt application. Open a project directory, see a tree of surveys, double-click one, and view an inline in a pyqtgraph section viewer with pan, zoom, colormap, and slice navigation across inline / xline / timeslice.

The point of M2 is to **prove the data layer drives a real GUI.** Not to build the final UI. Not to thread compute. Not to handle plugins. Just to show a section, swap slices, and change colors — backed by the `SeismicVolume` shipped in M1.

Stay disciplined and M2 is two or three focused weekends. Let it sprawl into "build the perfect viewer" and it'll eat M3.

## Exit criteria

You're done with M2 when this is true:

- `eggseis gui tests/data/projects/demo` launches a window.
- The project tree lists the demo survey. Double-click opens it in the section viewer.
- Pan, zoom, scroll inlines, switch to xline view, switch to timeslice view — all responsive.
- The View → Colormap menu changes the display.
- One headless end-to-end test (`pytest-qt` + `QT_QPA_PLATFORM=offscreen`) drives that workflow in CI on Linux/macOS/Windows.

---

## Locked design decisions for M2

| Area | Decision |
|---|---|
| Qt bindings | PySide6 (LGPL; matches ROADMAP) |
| 2D rendering | pyqtgraph |
| Project format | Plain directory, `project.yaml` manifest |
| Project save | **Out of scope** — open-only in M2; save deferred to M5 |
| Threading | **Out of scope** — synchronous render in M2; M4 owns compute/threading |
| GUI deps | Gated behind `gui` extra so headless CLI stays slim |
| Headless tests | `pytest-qt` + offscreen platform; no pixel asserts cross-OS |

---

## Step 1: Add GUI dependencies

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
gui = [
    "pyside6>=6.6",
    "pyqtgraph>=0.13",
    "pyyaml>=6.0",
]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-qt>=4.4",
    "ruff>=0.6",
    "mypy>=1.10",
    "eggseis[gui]",
]
```

`dev` pulls in `gui` so test runs always have Qt available. End users who only want the library or CLI install `eggseis` without extras.

Smoke test the install:

```bash
pip install -e ".[dev]"
python -c "from PySide6.QtWidgets import QApplication; print('ok')"
```

## Step 2: Project model

```python
# src/eggseis/project.py
"""Project model: a plain directory with a project.yaml manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SurveyEntry:
    name: str
    path: Path  # absolute, resolved from project.yaml location


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    surveys: tuple[SurveyEntry, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, project_dir: str | Path) -> Project:
        root = Path(project_dir).resolve()
        manifest = root / "project.yaml"
        if not manifest.is_file():
            raise FileNotFoundError(f"No project.yaml in {root}")
        data = yaml.safe_load(manifest.read_text())

        surveys = tuple(
            SurveyEntry(name=s["name"], path=(root / s["path"]).resolve())
            for s in data.get("surveys", [])
        )
        return cls(name=data["name"], root=root, surveys=surveys)
```

Minimum manifest:

```yaml
# project.yaml
name: F3 demo
surveys:
  - name: F3 fragment
    path: surveys/f3.mdio
horizons: []   # M5
wells: []      # M5
```

Paths relative to manifest. `horizons` and `wells` keys exist now so M5 doesn't break old projects.

## Step 3: Main window + menus

```python
# src/eggseis/app.py
"""Qt application entry point."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QSplitter

from eggseis.project import Project
from eggseis.viewers.section import SectionViewer
from eggseis.widgets.project_tree import ProjectTreeWidget
from eggseis.widgets.slice_nav import SliceNavigator


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("eggseis")
        self.resize(1200, 800)

        self.tree = ProjectTreeWidget()
        self.section_viewer = SectionViewer()
        self.slice_nav = SliceNavigator()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.section_viewer)
        right.addWidget(self.slice_nav)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menus()
        self._wire_signals()

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        a_open = QAction("&Open Project…", self)
        a_open.triggered.connect(self._on_open_project)
        a_quit = QAction("&Quit", self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_open)
        m_file.addSeparator()
        m_file.addAction(a_quit)

        m_view = self.menuBar().addMenu("&View")
        self._cmap_menu = m_view.addMenu("&Colormap")
        for name in ("gray", "seismic", "viridis"):
            a = QAction(name, self, checkable=True)
            a.triggered.connect(lambda _checked, n=name: self.set_colormap(n))
            self._cmap_menu.addAction(a)

        m_help = self.menuBar().addMenu("&Help")
        a_about = QAction("&About", self)
        m_help.addAction(a_about)

    def _wire_signals(self) -> None:
        self.tree.surveyActivated.connect(self.open_survey)
        self.slice_nav.sliceChanged.connect(self.section_viewer.show_slice)

    def _on_open_project(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Open Project")
        if d:
            self.open_project(Path(d))

    def open_project(self, path: Path) -> None:
        self.tree.set_project(Project.load(path))

    def open_survey(self, survey_path: Path) -> None:
        from eggseis.backends.mdio import MDIOBackend
        from eggseis.data import SeismicVolume

        volume = SeismicVolume(MDIOBackend(survey_path), name=survey_path.stem)
        self.section_viewer.set_volume(volume)
        self.slice_nav.set_geometry(volume.geometry)

    def set_colormap(self, name: str) -> None:
        self.section_viewer.set_colormap(name)
```

## Step 4: Project tree widget

```python
# src/eggseis/widgets/project_tree.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from eggseis.project import Project


class ProjectTreeWidget(QTreeWidget):
    surveyActivated = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabel("Project")
        self.itemDoubleClicked.connect(self._on_double_click)

    def set_project(self, project: Project) -> None:
        self.clear()
        root = QTreeWidgetItem([project.name])
        surveys = QTreeWidgetItem(["Surveys"])
        for s in project.surveys:
            item = QTreeWidgetItem([s.name])
            item.setData(0, 0x100, str(s.path))  # Qt.UserRole == 0x100
            surveys.addChild(item)
        root.addChild(surveys)
        root.addChild(QTreeWidgetItem(["Horizons"]))  # M5
        root.addChild(QTreeWidgetItem(["Wells"]))     # M5
        self.addTopLevelItem(root)
        root.setExpanded(True)
        surveys.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        path_str = item.data(0, 0x100)
        if path_str:
            self.surveyActivated.emit(Path(path_str))
```

## Step 5: Section viewer

```python
# src/eggseis/viewers/section.py
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout

from eggseis.colormaps import get_lut
from eggseis.data import SeismicVolume


class SectionViewer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.invertY(True)  # time increases downward
        self._image = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image)
        layout.addWidget(self._plot)

        self._volume: SeismicVolume | None = None
        self._lut_name = "gray"
        self._image.setLookupTable(get_lut(self._lut_name))

        # crosshair readout
        self._proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
        )

    @property
    def current_axis(self) -> str:
        return getattr(self, "_axis", "inline")

    @property
    def current_index(self) -> int:
        return getattr(self, "_index", 0)

    @property
    def lut_name(self) -> str:
        return self._lut_name

    def set_volume(self, volume: SeismicVolume) -> None:
        self._volume = volume
        g = volume.geometry
        self._axis = "inline"
        self._index = g.inline_min
        self._render()

    def show_slice(self, axis: str, index: int) -> None:
        self._axis = axis
        self._index = index
        self._render()

    def set_colormap(self, name: str) -> None:
        self._lut_name = name
        self._image.setLookupTable(get_lut(name))

    def _render(self) -> None:
        if self._volume is None:
            return
        if self._axis == "inline":
            arr = self._volume.read_inline(self._index)  # (n_xlines, n_samples)
        elif self._axis == "xline":
            arr = self._volume.read_xline(self._index)   # (n_inlines, n_samples)
        else:
            arr = self._volume.read_timeslice(self._index)  # (n_inlines, n_xlines)

        # transpose so time/depth axis is vertical for inline/xline views
        if self._axis in ("inline", "xline"):
            arr = arr.T
        # percentile stretch
        p_low, p_high = np.percentile(arr, [1, 99])
        self._image.setImage(arr, levels=(p_low, p_high))

    def _on_mouse_moved(self, evt) -> None:
        # surface (x, y) for status bar; left as a stub for M2
        ...
```

**Orientation convention** (lock now, document, test):

- Inline view: x-axis = xline number, y-axis = time (downward).
- Xline view: x-axis = inline number, y-axis = time (downward).
- Timeslice: x-axis = xline number, y-axis = inline number.

## Step 6: Slice navigator

```python
# src/eggseis/widgets/slice_nav.py
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from eggseis.data import SurveyGeometry


class SliceNavigator(QWidget):
    sliceChanged = Signal(str, int)  # axis, index

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)

        self.axis = QComboBox()
        self.axis.addItems(["inline", "xline", "timeslice"])
        self.spinbox = QSpinBox()
        self.spinbox.setEnabled(False)

        layout.addWidget(QLabel("Axis:"))
        layout.addWidget(self.axis)
        layout.addWidget(QLabel("Index:"))
        layout.addWidget(self.spinbox)
        layout.addStretch(1)

        self._geom: SurveyGeometry | None = None
        self.axis.currentTextChanged.connect(self._on_axis_changed)
        self.spinbox.valueChanged.connect(self._emit_change)

    def set_geometry(self, geom: SurveyGeometry) -> None:
        self._geom = geom
        self.spinbox.setEnabled(True)
        self._on_axis_changed(self.axis.currentText())

    def _on_axis_changed(self, axis: str) -> None:
        if self._geom is None:
            return
        g = self._geom
        if axis == "inline":
            lo, hi, step = g.inline_min, g.inline_max, g.inline_step
        elif axis == "xline":
            lo, hi, step = g.xline_min, g.xline_max, g.xline_step
        else:
            lo, hi, step = 0, g.n_samples - 1, 1
        self.spinbox.blockSignals(True)
        self.spinbox.setRange(lo, hi)
        self.spinbox.setSingleStep(step)
        self.spinbox.setValue(lo)
        self.spinbox.blockSignals(False)
        self._emit_change()

    def _emit_change(self) -> None:
        if self._geom is not None:
            self.sliceChanged.emit(self.axis.currentText(), self.spinbox.value())
```

## Step 7: Colormaps

```python
# src/eggseis/colormaps.py
from __future__ import annotations

import numpy as np

_LUTS: dict[str, np.ndarray] = {}


def _build_gray() -> np.ndarray:
    g = np.linspace(0, 255, 256, dtype=np.uint8)
    return np.stack([g, g, g, np.full_like(g, 255)], axis=1)


def _build_seismic() -> np.ndarray:
    # red-white-blue, white at center
    n = 256
    half = n // 2
    out = np.zeros((n, 4), dtype=np.uint8)
    out[:, 3] = 255
    out[:half, 0] = np.linspace(0, 255, half)        # R 0→255
    out[:half, 1] = np.linspace(0, 255, half)        # G 0→255
    out[:half, 2] = 255                              # B 255
    out[half:, 0] = 255                              # R 255
    out[half:, 1] = np.linspace(255, 0, n - half)    # G 255→0
    out[half:, 2] = np.linspace(255, 0, n - half)    # B 255→0
    return out


def _build_viridis() -> np.ndarray:
    from matplotlib import colormaps  # only used if matplotlib is present
    cmap = colormaps["viridis"]
    return (cmap(np.linspace(0, 1, 256)) * 255).astype(np.uint8)


_BUILDERS = {"gray": _build_gray, "seismic": _build_seismic, "viridis": _build_viridis}


def get_lut(name: str) -> np.ndarray:
    if name not in _LUTS:
        _LUTS[name] = _BUILDERS[name]()
    return _LUTS[name]
```

If pulling matplotlib in just for viridis bothers you, hand-roll a viridis polynomial approximation — cheap, no dep. Decide once, move on.

## Step 8: CLI subcommand

Add `gui` to `src/eggseis/cli.py`:

```python
@app.command()
def gui(
    project_dir: Path | None = typer.Argument(None, help="Optional project directory"),
) -> None:
    """Launch the eggseis GUI."""
    import sys

    from PySide6.QtWidgets import QApplication

    from eggseis.app import MainWindow

    qt_app = QApplication(sys.argv)
    win = MainWindow()
    if project_dir is not None:
        win.open_project(project_dir)
    win.show()
    sys.exit(qt_app.exec())
```

`eggseis gui tests/data/projects/demo` should boot.

## Step 9: Tests

### 9a — unit tests (no Qt)

```python
# tests/test_project.py
from eggseis.project import Project


def test_load_minimal_project(tmp_path):
    (tmp_path / "project.yaml").write_text(
        "name: T\nsurveys:\n  - name: A\n    path: a.mdio\nhorizons: []\nwells: []\n"
    )
    proj = Project.load(tmp_path)
    assert proj.name == "T"
    assert len(proj.surveys) == 1
    assert proj.surveys[0].path == (tmp_path / "a.mdio").resolve()
```

### 9b — headless GUI smoke test

```python
# tests/test_gui_smoke.py
import os
import pytest
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402

from eggseis.app import MainWindow  # noqa: E402


def test_open_project_and_swap_slice(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)

    # double-click first survey
    surveys_item = win.tree.topLevelItem(0).child(0)  # "Surveys"
    survey_item = surveys_item.child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)

    qtbot.waitUntil(lambda: win.section_viewer._volume is not None)

    # swap slice axis
    win.slice_nav.axis.setCurrentText("xline")
    assert win.section_viewer.current_axis == "xline"

    # swap colormap
    win.set_colormap("seismic")
    assert win.section_viewer.lut_name == "seismic"
```

`demo_project_path` fixture builds `tests/data/projects/demo/` with a `project.yaml` pointing at the synthetic MDIO already produced by `sample_mdio_path`.

### Test conventions (lock now)

- All Qt tests use `qtbot.waitSignal` / `qtbot.waitUntil`. **No `time.sleep`.**
- **No pixel-exact asserts** cross-OS. Test signals, state, and structure — not rendered pixels.
- Mark Qt tests with `@pytest.mark.gui` if you ever want to skip them in a non-Qt env.

## Step 10: Sample project fixture

```
tests/data/projects/demo/
├── project.yaml
└── surveys/
    └── synth.mdio       # built at test time from the M1 synthetic fixture
```

`conftest.py` extends:

```python
@pytest.fixture(scope="session")
def demo_project_path(tmp_path_factory, sample_mdio_path):
    root = tmp_path_factory.mktemp("project")
    surveys = root / "surveys"
    surveys.mkdir()
    # copy or symlink the synthetic mdio
    import shutil
    target = surveys / "synth.mdio"
    shutil.copytree(sample_mdio_path, target)
    (root / "project.yaml").write_text(
        f"name: demo\nsurveys:\n  - name: synth\n    path: surveys/synth.mdio\n"
        f"horizons: []\nwells: []\n"
    )
    return root
```

## Step 11: CI

Update `.github/workflows/tests.yml`:

```yaml
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.11", "3.12"]
    env:
      QT_QPA_PLATFORM: offscreen
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Test
        run: pytest
```

Linux runners need libGL / libxcb deps for PySide6's Qt libs even in offscreen mode. If install fails on Linux:

```yaml
- if: runner.os == 'Linux'
  run: sudo apt-get install -y libegl1 libxkbcommon0 libdbus-1-3
```

Add only if needed — recent PySide6 wheels generally bundle enough.

---

## Execution order

1. Add `gui` extra to `pyproject.toml`. Run `pip install -e ".[dev]"`. Smoke test PySide6 import.
2. Write `project.py` + tests.
3. Write `colormaps.py` + tests for shape.
4. Build `MainWindow` skeleton with menus stubbed. `eggseis gui` launches an empty window.
5. Add `ProjectTreeWidget`. Open a project, see the tree.
6. Add `SectionViewer`. Wire `tree.surveyActivated → window.open_survey → viewer.set_volume`. See an inline.
7. Add `SliceNavigator`. Switch axes, scroll slices.
8. Wire colormap menu. Swap LUTs.
9. Write `tests/test_gui_smoke.py`. Run with `QT_QPA_PLATFORM=offscreen`.
10. Update CI. Watch matrix go green.

Two or three weekends. Don't let any single step block you for more than a few hours — if Qt or pyqtgraph fights you, ship the smallest thing that paints something and refine.

---

## Risks

- **Qt + Linux CI** — offscreen platform usually works; may need apt deps for `libegl1` / `libxkbcommon0`. Solved problem.
- **pyqtgraph perf on big inlines** — synchronous render is fine for M2; threading lands in M4. If demo data is large enough that synchronous render lags, downsample for display only.
- **PySide6 wheel size** — keep behind `gui` extra so library users pay nothing.
- **Image orientation drift** — easy to flip an axis once and never notice. Add an assertion in the smoke test that `section_viewer._image.image.shape` matches the expected `(n_samples, n_xlines)` for an inline.
- **Volume viewer (M6) will be harder** — PyVista/VTK needs a real GL context. Plan to add `LIBGL_ALWAYS_SOFTWARE=1` then. Not an M2 problem.

---

## Out of scope for M2

- Project save / persistent UI state → M5.
- Threading / debounce / cancellation / cache → M4.
- Plugin menu, attributes → M3.
- Volume viewer, crossplot → M6 / M7.
- Horizon / well overlays → M5.
- Crosshair status-bar readout text — stub the slot, fill in M3 if it's still missing.

---

## When M2 is done

A clean exit looks like:

- `eggseis gui tests/data/projects/demo` opens a window with a tree + viewer.
- The headless smoke test passes on Linux, macOS, and Windows in CI.
- README screenshot updated with the new section view.
- CHANGELOG.md gets an entry under `[v0.1.0a2]`.
- Tag `v0.1.0a2` on `main` after the M2 PR merges.
- Take a beat. Then start M3 — "The plugin runs."
