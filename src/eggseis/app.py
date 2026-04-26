"""Qt application — main window for the section viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QSplitter

from eggseis.axes import Axis
from eggseis.backends.mdio import MDIOBackend
from eggseis.colormaps import LUTS_AVAILABLE
from eggseis.data import SeismicVolume
from eggseis.project import Project
from eggseis.viewers.section import DEFAULT_LUT, SectionViewer
from eggseis.widgets.project_tree import ProjectTreeWidget
from eggseis.widgets.slice_nav import SliceNavigator

_BIG_STEP = 10


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("eggseis")
        self.resize(1200, 800)

        self.tree = ProjectTreeWidget()
        self.section_viewer = SectionViewer()
        self.slice_nav = SliceNavigator()

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.section_viewer)
        right.addWidget(self.slice_nav)
        right.setStretchFactor(0, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._project: Project | None = None
        self._build_menus()
        self._wire_signals()
        self._build_shortcuts()

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
        cmap_menu = m_view.addMenu("&Colormap")
        self._cmap_group = QActionGroup(self)
        self._cmap_group.setExclusive(True)
        for name in LUTS_AVAILABLE:
            a = QAction(name, self, checkable=True)
            a.setChecked(name == DEFAULT_LUT)
            a.triggered.connect(lambda _checked, n=name: self.set_colormap(n))
            self._cmap_group.addAction(a)
            cmap_menu.addAction(a)

        m_help = self.menuBar().addMenu("&Help")
        m_help.addAction(QAction("&About", self))

    def _build_shortcuts(self) -> None:
        bindings = (
            ("Left", lambda: self.slice_nav.step(-1)),
            ("Right", lambda: self.slice_nav.step(+1)),
            ("PgUp", lambda: self.slice_nav.step(-_BIG_STEP)),
            ("PgDown", lambda: self.slice_nav.step(+_BIG_STEP)),
            ("I", lambda: self.slice_nav.set_axis(Axis.INLINE)),
            ("X", lambda: self.slice_nav.set_axis(Axis.XLINE)),
            ("T", lambda: self.slice_nav.set_axis(Axis.TIMESLICE)),
        )
        for keys, slot in bindings:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(slot)

    def _wire_signals(self) -> None:
        self.tree.surveyActivated.connect(self.open_survey)
        self.slice_nav.sliceChanged.connect(self.section_viewer.show_slice)
        self.section_viewer.cursorMoved.connect(self.statusBar().showMessage)

    @property
    def project(self) -> Project | None:
        return self._project

    def _on_open_project(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Open Project")
        if not d:
            return
        try:
            self.open_project(Path(d))
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Open Project failed", str(exc))

    def open_project(self, path: str | Path) -> None:
        self._project = Project.load(path)
        self.tree.set_project(self._project)
        self.setWindowTitle(f"eggseis — {self._project.name}")

    def open_survey(self, survey_path: Path) -> None:
        volume = SeismicVolume(MDIOBackend(survey_path), name=survey_path.stem)
        self.section_viewer.set_volume(volume)
        self.slice_nav.set_geometry(volume.geometry)

    def set_colormap(self, name: str) -> None:
        self.section_viewer.set_colormap(name)
