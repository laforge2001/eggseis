"""Empty-state widget shown when no project is loaded."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from eggseis.recent import load_recent


class WelcomeWidget(QWidget):
    openProjectRequested = Signal()
    newProjectRequested = Signal()
    recentRequested = Signal(str)  # absolute path

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        glyph = QLabel("○ ∿")
        glyph.setStyleSheet("font-size: 48px; color: palette(mid);")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("No project loaded")
        title.setStyleSheet("font-size: 16px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QHBoxLayout()
        self._open_button = QPushButton("Open Project ⌘O")
        self._open_button.clicked.connect(self.openProjectRequested.emit)
        self._new_button = QPushButton("New Project")
        self._new_button.clicked.connect(self.newProjectRequested.emit)
        buttons.addStretch(1)
        buttons.addWidget(self._open_button)
        buttons.addWidget(self._new_button)
        buttons.addStretch(1)

        recent_title = QLabel("Recent")
        recent_title.setStyleSheet(
            "color: palette(mid); font-size: 11px; text-transform: uppercase;"
        )
        self._recent_list = QListWidget()
        self._recent_list.setMaximumHeight(120)
        self._recent_list.itemClicked.connect(self._on_recent_clicked)
        self.refresh()

        layout.addStretch(1)
        layout.addWidget(glyph)
        layout.addWidget(title)
        layout.addSpacing(18)
        layout.addLayout(buttons)
        layout.addSpacing(36)
        layout.addWidget(recent_title)
        layout.addWidget(self._recent_list)
        layout.addStretch(1)

    def refresh(self) -> None:
        self._recent_list.clear()
        for entry in load_recent():
            path = entry["path"]
            label = f"{Path(path).name}  —  {path}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._recent_list.addItem(item)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.recentRequested.emit(path)
