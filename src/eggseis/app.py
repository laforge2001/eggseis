"""Qt application — main window for the section viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
)

from eggseis.axes import Axis
from eggseis.backends.mdio import MDIOBackend
from eggseis.colormaps import LUTS_AVAILABLE
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.data import SeismicVolume
from eggseis.graph.canvas import GraphCanvas
from eggseis.graph.executor import GraphExecutor
from eggseis.graph.model import SOURCE_ID, Graph
from eggseis.graph.params_popup import NodeParamsPopup
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
        self.param_dock = ParamDock()  # Legacy single-attribute param editor.

        # Three-pane layout:
        #   tree (far left) | section viewer + slice nav (center) | graph canvas (right)
        viewer_pane = QSplitter(Qt.Vertical)
        viewer_pane.addWidget(self.section_viewer)
        viewer_pane.addWidget(self.slice_nav)
        viewer_pane.setStretchFactor(0, 1)

        self._canvas = GraphCanvas()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(viewer_pane)
        splitter.addWidget(self._canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([220, 600, 380])
        self.setCentralWidget(splitter)

        # Legacy Attribute-menu param dock kept around for the menu-driven
        # path but hidden by default. Floats if the user enables it.
        self._param_dock_widget = QDockWidget("Parameters (legacy)", self)
        self._param_dock_widget.setWidget(self.param_dock)
        self._param_dock_widget.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self._param_dock_widget)
        self.param_dock.setMinimumWidth(260)
        self._param_dock_widget.setVisible(False)

        self._project: Project | None = None
        self._active_plugin: PluginSpec | None = None
        self._active_params = None
        self._plugin_actions: dict[str, QAction] = {}
        self._compute = JobOrchestrator()
        self._compute_errors: list[tuple[str, str]] = []
        self._compute.tilesReady.connect(self._on_tiles_ready)
        self._compute.sectionReady.connect(self._on_section_ready)
        self._compute.failed.connect(self._on_compute_failed)

        self._executor = GraphExecutor(self._compute)
        self._executor.tapReady.connect(self._on_tap_ready)
        self._executor.failed.connect(self._on_chain_failed)
        self._executor.progress.connect(self._on_chain_progress)

        self._graphs: dict[str, Graph] = {}
        self._active_survey_id: str | None = None
        self._canvas.edgeChanged.connect(self._request_tap)
        self._canvas.tapPortChanged.connect(lambda _id, _port: self._request_tap())
        # Pre-register every discovered plugin so qtpynodeeditor's
        # right-click "Add Node" menu shows the full library.
        self._canvas.register_specs(discover_all())
        # Auto-tap any newly added node (covers menu adds and right-click).
        self._canvas.nodeAdded.connect(lambda nid: self._canvas.set_tap(nid, "out"))

        # Double-click → modeless params popup. Replaces the previous tap-on-
        # double-click behaviour; tap stays on the right-click context menu.
        self._params_popups: dict[str, NodeParamsPopup] = {}
        self._canvas._scene.node_double_clicked.connect(self._on_node_double_clicked_open_params)
        self._canvas.nodeRemoved.connect(self._close_popup_for_node)
        self._canvas._scene.node_context_menu.connect(self._on_node_context_menu)

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

        m_graph = self.menuBar().addMenu("&Graph")
        a_add_node = QAction("&Add Plugin to Graph…", self)
        a_add_node.triggered.connect(self._on_add_node_to_graph)
        m_graph.addAction(a_add_node)
        m_graph.addSeparator()
        a_export = QAction("&Export Volume with Graph Applied…", self)
        a_export.triggered.connect(self._on_export_volume)
        m_graph.addAction(a_export)

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

    def _show_errors_dialog(
        self, title: str, summary: str, empty_message: str, body_lines: list[str]
    ) -> None:
        if not body_lines:
            QMessageBox.information(self, title, empty_message)
            return
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(summary)
        box.setDetailedText("\n\n".join(body_lines))
        box.exec()

    def _on_show_plugin_errors(self) -> None:
        self._show_errors_dialog(
            title="Plugin Errors",
            summary=f"{len(self._plugin_load_errors)} plugin(s) failed to load:",
            empty_message="No plugin load errors recorded.",
            body_lines=[
                f"• {err.source}\n    {err.message}"
                for err in self._plugin_load_errors
            ],
        )

    def _on_show_compute_errors(self) -> None:
        self._show_errors_dialog(
            title="Compute Errors",
            summary=f"{len(self._compute_errors)} compute error(s) this session:",
            empty_message="No compute errors recorded this session.",
            body_lines=[f"• {name}\n    {msg}" for name, msg in self._compute_errors],
        )

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
        # Visual feedback first: status bar + busy progress + wait cursor.
        # processEvents pumps the GUI so the user sees the indicator before
        # the synchronous backend open + first inline read block the thread.
        self.statusBar().showMessage(f"Loading {survey_path.name}…")
        progress = QProgressDialog(
            f"Loading {survey_path.name}…", None, 0, 0, self
        )
        progress.setWindowTitle("Open Survey")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        QApplication.processEvents()

        try:
            volume = SeismicVolume(MDIOBackend(survey_path), name=survey_path.stem)
            survey_id = str(survey_path.resolve())
            self._active_survey_id = survey_id
            self._graphs.setdefault(survey_id, Graph())
            self.section_viewer.set_volume(volume)
            self.slice_nav.set_geometry(volume.geometry)
            self._canvas.bind(self._graphs[survey_id])
            for popup in list(self._params_popups.values()):
                popup.close()
            self._params_popups.clear()
            if self._graphs[survey_id].nodes:
                self._request_tap()
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
            self.statusBar().showMessage(f"Loaded {survey_path.name}", 3000)

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
        # show_slice clears overlay internally; if a graph or plugin is
        # active, recompute. The graph-driven path takes precedence over
        # the menu-driven single-attribute path so we don't paint twice.
        self.section_viewer.show_slice(axis, index)
        graph = (
            self._graphs.get(self._active_survey_id)
            if self._active_survey_id else None
        )
        if graph is not None and graph.nodes:
            self._request_tap()
        elif self._active_plugin is not None:
            self._recompute_overlay()

    def _on_params_changed(self, params) -> None:
        if self._active_plugin is None:
            return
        self._active_params = params
        self._recompute_overlay(params)

    def _recompute_overlay(self, params=None) -> None:
        spec = self._active_plugin
        volume = self.section_viewer.volume
        if spec is None or volume is None:
            return
        if params is None:
            params = (
                self._active_params if self._active_params is not None
                else spec.param_model()
            )
        self._compute.request(
            spec,
            params,
            volume,
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
        self._compute_errors_action.setText(
            f"&Compute Errors… ({len(self._compute_errors)})"
        )
        self.statusBar().showMessage(f"{name} failed: {message}", 5000)

    def add_plugin_to_graph(self, spec: PluginSpec) -> str | None:
        """Add a node for `spec` to the active survey's graph + canvas.

        Auto-tap is wired through canvas.nodeAdded -> set_tap so this is the
        same flow whether the node arrives via the Graph menu or the canvas
        right-click 'Add Node' submenu. Returns the new node_id, or None
        if no survey is active.
        """
        if self._active_survey_id is None:
            return None
        return self._canvas.add_plugin(spec)

    def _on_node_double_clicked_open_params(self, scene_node) -> None:
        node_id = self._canvas._scene_node_to_graph_id(scene_node)
        if node_id is None or node_id == SOURCE_ID:
            return
        graph = self._graphs[self._active_survey_id]
        node = graph.nodes[node_id]

        existing = self._params_popups.get(node_id)
        if existing is not None and not existing.isHidden():
            existing.raise_()
            existing.activateWindow()
            return

        popup = NodeParamsPopup(node, parent=self)
        popup.paramsChanged.connect(self._on_node_params_changed)
        popup.finished.connect(lambda _result, nid=node_id: self._params_popups.pop(nid, None))
        self._params_popups[node_id] = popup
        popup.show()

    def _close_popup_for_node(self, node_id: str) -> None:
        popup = self._params_popups.pop(node_id, None)
        if popup is not None:
            popup.close()

    def _on_node_context_menu(self, scene_node, _scene_pos, screen_pos) -> None:
        node_id = self._canvas._scene_node_to_graph_id(scene_node)
        if node_id is None or node_id == SOURCE_ID:
            return
        graph = self._graphs[self._active_survey_id]
        node = graph.nodes[node_id]
        is_multi_input = len(node.spec.inputs) > 1

        menu = QMenu(self)
        if is_multi_input:
            action_disable = QAction("Disable (multi-input not allowed)", self)
            action_disable.setEnabled(False)
            menu.addAction(action_disable)
        else:
            label = "Enable" if not node.enabled else "Disable"
            action_toggle = QAction(label, self)
            action_toggle.triggered.connect(
                lambda _checked, nid=node_id, on=not node.enabled:
                    self._canvas.set_node_enabled(nid, on)
            )
            menu.addAction(action_toggle)
        action_tap = QAction("Tap output", self)
        action_tap.triggered.connect(
            lambda _checked, nid=node_id: self._canvas.set_tap(nid, "out")
        )
        menu.addAction(action_tap)
        menu.addSeparator()
        action_remove = QAction("Remove node", self)
        action_remove.triggered.connect(
            lambda _checked, nid=node_id: self._canvas.remove_node(nid)
        )
        menu.addAction(action_remove)
        menu.exec_(screen_pos)

    def _on_export_volume(self) -> None:
        from eggseis.graph.runner import export_volume_with_graph

        if self._active_survey_id is None:
            self.statusBar().showMessage("Open a survey first.", 3000)
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Volume", "", "MDIO (*.mdio);;All files (*)"
        )
        if not out_path:
            return
        graph = self._graphs[self._active_survey_id]
        volume = self.section_viewer.volume
        n_il = volume.geometry.n_inlines

        progress = QProgressDialog(
            "Exporting volume with graph applied…", "Cancel", 0, n_il, self
        )
        progress.setWindowTitle("Export")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        cancelled = {"v": False}

        def on_progress(done: int, total: int) -> None:
            progress.setValue(done)
            if progress.wasCanceled():
                cancelled["v"] = True
                raise InterruptedError("export cancelled by user")

        try:
            export_volume_with_graph(graph, volume, out_path, on_progress=on_progress)
        except InterruptedError:
            self.statusBar().showMessage("Export cancelled.", 3000)
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", repr(exc))
            return
        progress.setValue(n_il)
        self.statusBar().showMessage(f"Wrote {out_path}", 5000)

    def _on_add_node_to_graph(self) -> None:
        if self._active_survey_id is None:
            self.statusBar().showMessage("Open a survey first.", 3000)
            return
        specs = sorted(discover_all(), key=lambda s: s.name)
        if not specs:
            return
        names = [s.name for s in specs]
        choice, ok = QInputDialog.getItem(
            self, "Add Plugin to Graph", "Plugin:", names, 0, False
        )
        if not ok:
            return
        spec = next(s for s in specs if s.name == choice)
        self.add_plugin_to_graph(spec)

    def _on_node_params_changed(self, node_id: str, params) -> None:
        graph = (
            self._graphs.get(self._active_survey_id)
            if self._active_survey_id else None
        )
        if graph is None or node_id not in graph.nodes:
            return
        graph.set_params(node_id, params)
        self._request_tap()

    def _request_tap(self) -> None:
        volume = self.section_viewer.volume
        if volume is None or self._active_survey_id is None:
            return
        graph = self._graphs[self._active_survey_id]
        if not graph.nodes or graph.tap_port[0] == SOURCE_ID:
            # Empty graph or Source-tap — section viewer paints raw via
            # show_slice. Skip the executor to avoid stamping a redundant
            # raw overlay.
            self.section_viewer.clear_overlay()
            return
        # Mid-wiring: the user has tapped a node whose inputs aren't all
        # connected yet. Stay on raw rather than firing a failed signal —
        # the executor would just emit "input port unconnected".
        tap_node, _ = graph.tap_port
        if not self._cone_fully_wired(graph, tap_node):
            self.section_viewer.clear_overlay()
            return
        self._executor.request_tap(
            graph,
            volume,
            self.section_viewer.current_axis,
            self.section_viewer.current_index,
        )

    def _cone_fully_wired(self, graph: Graph, tap_node: str) -> bool:
        from eggseis.graph.model import SOURCE_ID as _SRC
        for nid in graph.upstream_cone(tap_node, "out"):
            if nid == _SRC:
                continue
            node = graph.nodes[nid]
            incoming = graph.incoming_edges(nid)
            for port in node.spec.inputs:
                if port not in incoming:
                    return False
        return True

    def _on_chain_progress(self, current: int, total: int, name: str) -> None:
        self.statusBar().showMessage(f"Computing {current} of {total}: {name}…")

    def _on_tap_ready(self, _job_id: int, arr) -> None:
        self.section_viewer.set_overlay(arr, partial=False)
        self.statusBar().clearMessage()

    def _on_chain_failed(self, _job_id: int, message: str) -> None:
        self._compute_errors.append(("chain", message))
        self._compute_errors_action.setText(
            f"&Compute Errors… ({len(self._compute_errors)})"
        )
        self.statusBar().showMessage(f"Pipeline failed: {message}", 5000)
