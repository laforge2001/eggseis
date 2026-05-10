"""Project tree widget — surveys / horizons / wells."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from eggseis.project import Project

_PATH_ROLE = Qt.ItemDataRole.UserRole
_HORIZON_NAME_ROLE = Qt.ItemDataRole.UserRole + 1
_WELL_NAME_ROLE = Qt.ItemDataRole.UserRole + 2


class ProjectTreeWidget(QTreeWidget):
    surveyActivated = Signal(Path)
    horizonActivated = Signal(str)
    wellActivated = Signal(str)
    loadRequested = Signal(str)  # category name: "survey", "horizon", or "well"

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabel("Project")
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_project(self, project: Project) -> None:
        self.clear()
        root = QTreeWidgetItem([project.name])
        surveys = QTreeWidgetItem(["Surveys"])
        for s in project.surveys:
            item = QTreeWidgetItem([s.name])
            item.setData(0, _PATH_ROLE, str(s.path))
            surveys.addChild(item)
        root.addChild(surveys)

        horizons = QTreeWidgetItem(["Horizons"])
        for h in project.horizons:
            item = QTreeWidgetItem([h.name])
            item.setData(0, _HORIZON_NAME_ROLE, h.name)
            horizons.addChild(item)
        root.addChild(horizons)

        wells = QTreeWidgetItem(["Wells"])
        for w in project.wells:
            item = QTreeWidgetItem([w.name])
            item.setData(0, _WELL_NAME_ROLE, w.name)
            wells.addChild(item)
        root.addChild(wells)

        self.addTopLevelItem(root)
        root.setExpanded(True)
        surveys.setExpanded(True)
        horizons.setExpanded(True)
        wells.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        path_str = item.data(0, _PATH_ROLE)
        if path_str:
            self.surveyActivated.emit(Path(path_str))
            return
        horizon_name = item.data(0, _HORIZON_NAME_ROLE)
        if horizon_name:
            self.horizonActivated.emit(str(horizon_name))
            return
        well_name = item.data(0, _WELL_NAME_ROLE)
        if well_name:
            self.wellActivated.emit(str(well_name))

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        text = item.text(0)
        category_map = {"Surveys": "survey", "Horizons": "horizon", "Wells": "well"}
        category = category_map.get(text)
        if category is None:
            return
        menu = QMenu(self)
        action = QAction("Load…", self)
        action.triggered.connect(
            lambda _checked=False, c=category: self.loadRequested.emit(c)
        )
        menu.addAction(action)
        menu.exec_(self.mapToGlobal(pos))
