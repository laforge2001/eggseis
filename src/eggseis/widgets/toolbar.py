"""Primary toolbar: open / save | import survey / horizon / well | add plugin / export."""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar

_ICONS = {
    "open": "fa5s.folder-open",
    "save": "fa5s.save",
    "import_survey": "fa5s.cube",
    "import_horizon": "fa5s.chart-area",
    "import_well": "fa5s.tint",
    "add_plugin": "fa5s.puzzle-piece",
    "export_volume": "fa5s.upload",
}

_GATED = {"save", "import_survey", "import_horizon", "import_well", "add_plugin", "export_volume"}


class PrimaryToolbar(QToolBar):
    def __init__(self, actions: dict[str, QAction]) -> None:
        super().__init__("Primary")
        self.setMovable(False)
        self._actions: dict[str, QAction] = {}

        for group in (
            ("open", "save"),
            ("import_survey", "import_horizon", "import_well"),
            ("add_plugin", "export_volume"),
        ):
            for name in group:
                action = actions[name]
                action.setIcon(qta.icon(_ICONS[name]))
                self.addAction(action)
                self._actions[name] = action
            self.addSeparator()

    def set_project_loaded(self, loaded: bool) -> None:
        for name in _GATED:
            self._actions[name].setEnabled(loaded)

    def _action_for(self, name: str) -> QAction:
        return self._actions[name]
