"""Qt application — main window for the section viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
)

from eggseis.axes import Axis
from eggseis.backends.mdio import MDIOBackend
from eggseis.colormaps import LUTS_AVAILABLE
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec
from eggseis.plugin_loader import discover_all, load_errors
from eggseis.plugin_template import create_template, open_in_editor
from eggseis.project import Project
from eggseis.viewers.section import DEFAULT_LUT, SectionViewer
from eggseis.widgets.param_dock import ParamDock
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
        self.param_dock = ParamDock()

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.section_viewer)
        right.addWidget(self.slice_nav)
        right.setStretchFactor(0, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._param_dock_widget = QDockWidget("Parameters", self)
        self._param_dock_widget.setWidget(self.param_dock)
        self._param_dock_widget.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self._param_dock_widget)
        self.param_dock.setMinimumWidth(260)

        self._project: Project | None = None
        self._active_plugin: PluginSpec | None = None
        self._active_params = None
        self._plugin_actions: dict[str, QAction] = {}
        self._compute = JobOrchestrator()
        self._compute_errors: list[tuple[str, str]] = []
        self._compute.tilesReady.connect(self._on_tiles_ready)
        self._compute.sectionReady.connect(self._on_section_ready)
        self._compute.failed.connect(self._on_compute_failed)
        self._build_menus()
        self._wire_signals()
        self._build_shortcuts()

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        a_open = QAction("&Open Project…", self)
        a_open.triggered.connect(self._on_open_project)
        a_new_plugin = QAction("&New Plugin…", self)
        a_new_plugin.triggered.connect(self._on_new_plugin)
        a_quit = QAction("&Quit", self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_open)
        m_file.addAction(a_new_plugin)
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
        m_view.addSeparator()
        self._lock_levels_action = QAction("&Lock Levels to Raw", self, checkable=True)
        self._lock_levels_action.setChecked(self.section_viewer.levels_locked)
        self._lock_levels_action.toggled.connect(self.section_viewer.set_levels_locked)
        m_view.addAction(self._lock_levels_action)

        m_attr = self.menuBar().addMenu("&Attribute")
        self._attr_group = QActionGroup(self)
        self._attr_group.setExclusive(True)
        a_none = QAction("None (raw amplitude)", self, checkable=True)
        a_none.setChecked(True)
        a_none.triggered.connect(lambda: self._activate_plugin(None))
        self._attr_group.addAction(a_none)
        m_attr.addAction(a_none)
        m_attr.addSeparator()
        for spec in sorted(discover_all(), key=lambda s: s.name):
            a = QAction(spec.name, self, checkable=True)
            a.triggered.connect(lambda _checked, s=spec: self._activate_plugin(s))
            self._attr_group.addAction(a)
            m_attr.addAction(a)
            self._plugin_actions[spec.id] = a
        # Snapshot errors collected during discover_all() above.
        self._plugin_load_errors = load_errors()

        m_help = self.menuBar().addMenu("&Help")
        m_help.addAction(QAction("&About", self))
        a_errors = QAction("&Plugin Errors…", self)
        a_errors.triggered.connect(self._on_show_plugin_errors)
        a_errors.setEnabled(bool(self._plugin_load_errors))
        if self._plugin_load_errors:
            a_errors.setText(f"&Plugin Errors… ({len(self._plugin_load_errors)})")
        self._plugin_errors_action = a_errors
        m_help.addAction(a_errors)

        a_compute_errors = QAction("&Compute Errors…", self)
        a_compute_errors.triggered.connect(self._on_show_compute_errors)
        m_help.addAction(a_compute_errors)
        self._compute_errors_action = a_compute_errors

        if self._plugin_load_errors:
            # Surface a transient hint so users don't miss it.
            self.statusBar().showMessage(
                f"{len(self._plugin_load_errors)} plugin(s) failed to load — "
                "see Help → Plugin Errors",
                10000,
            )

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
        self.slice_nav.sliceChanged.connect(self._on_slice_changed)
        self.section_viewer.cursorMoved.connect(self.statusBar().showMessage)
        self.param_dock.paramsChanged.connect(self._on_params_changed)

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

    def _on_show_plugin_errors(self) -> None:
        if not self._plugin_load_errors:
            QMessageBox.information(
                self, "Plugin Errors", "No plugin load errors recorded."
            )
            return
        body = "\n\n".join(
            f"• {err.source}\n    {err.message}" for err in self._plugin_load_errors
        )
        box = QMessageBox(self)
        box.setWindowTitle("Plugin Errors")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{len(self._plugin_load_errors)} plugin(s) failed to load:")
        box.setDetailedText(body)
        box.exec()

    def _on_show_compute_errors(self) -> None:
        if not self._compute_errors:
            QMessageBox.information(
                self, "Compute Errors", "No compute errors recorded this session."
            )
            return
        body = "\n\n".join(f"• {name}\n    {msg}" for name, msg in self._compute_errors)
        box = QMessageBox(self)
        box.setWindowTitle("Compute Errors")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{len(self._compute_errors)} compute error(s) this session:")
        box.setDetailedText(body)
        box.exec()

    def _on_new_plugin(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New Plugin", "Plugin display name (e.g. 'My Filter'):"
        )
        if not ok or not name.strip():
            return
        try:
            path = create_template(name.strip())
        except FileExistsError as exc:
            QMessageBox.warning(self, "New Plugin", f"Already exists: {exc}")
            return
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "New Plugin failed", str(exc))
            return
        open_in_editor(path)
        QMessageBox.information(
            self,
            "Plugin created",
            f"Wrote {path}\n\nEdit the file, then restart eggseis to register it.",
        )

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

    @property
    def active_plugin(self) -> PluginSpec | None:
        return self._active_plugin

    def _activate_plugin(self, spec: PluginSpec | None) -> None:
        self._active_plugin = spec
        self._active_params = None
        self.param_dock.set_plugin(spec)
        if spec is None:
            self.section_viewer.clear_overlay()

    def _on_slice_changed(self, axis, index) -> None:
        # show_slice clears overlay internally; if a plugin is active, recompute.
        self.section_viewer.show_slice(axis, index)
        if self._active_plugin is not None:
            self._recompute_overlay()

    def _on_params_changed(self, params) -> None:
        if self._active_plugin is None:
            return
        self._active_params = params
        self._recompute_overlay(params)

    def _recompute_overlay(self, params=None) -> None:
        spec = self._active_plugin
        if spec is None or not self.section_viewer.has_volume:
            return
        if params is None:
            params = self._active_params or spec.param_model()
        self._compute.request(
            spec,
            params,
            self.section_viewer._volume,
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )

    def _on_tiles_ready(self, _job_id: int, buffer, _ranges) -> None:
        self.section_viewer.set_overlay(buffer, partial=True)

    def _on_section_ready(self, _job_id: int, arr) -> None:
        self.section_viewer.set_overlay(arr, partial=False)

    def _on_compute_failed(self, _job_id: int, message: str) -> None:
        spec = self._active_plugin
        name = spec.name if spec else "compute"
        self._compute_errors.append((name, message))
        self.statusBar().showMessage(f"{name} failed: {message}", 5000)
