"""Project tree widget — surveys / horizons / wells."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from eggseis.project import Project

_PATH_ROLE = Qt.ItemDataRole.UserRole


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
            item.setData(0, _PATH_ROLE, str(s.path))
            surveys.addChild(item)
        root.addChild(surveys)

        horizons = QTreeWidgetItem([f"Horizons ({len(project.horizons)})"])
        for h in project.horizons:
            horizons.addChild(QTreeWidgetItem([h.name]))
        root.addChild(horizons)

        wells = QTreeWidgetItem([f"Wells ({len(project.wells)})"])
        for w in project.wells:
            wells.addChild(QTreeWidgetItem([w.name]))
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
