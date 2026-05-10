"""Project load with missing plugins / horizons.

The Graph.from_dict orphan errors are exercised in test_graph_model.py
(OrphanPluginError) and test_horizon_graph_node.py (OrphanHorizonError).
This module covers the GUI recovery dialog: MainWindow._prompt_orphan_recovery
should return "skip" or "abort" depending on which button the user clicks.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QMessageBox

from eggseis.app import MainWindow


def test_prompt_orphan_recovery_skip(qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)

    captured: dict[str, object] = {}

    def fake_exec(self):
        # Pick the AcceptRole ("Skip") button.
        for btn in self.buttons():
            if self.buttonRole(btn) == QMessageBox.ButtonRole.AcceptRole:
                captured["skip_btn"] = btn
                # Simulate clicking it so clickedButton() reports it back.
                self.setProperty("_eggseis_clicked", btn)
                return 0
        return 0

    def fake_clicked_button(self):
        return self.property("_eggseis_clicked")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)

    action = win._prompt_orphan_recovery(
        "Missing plugin", "tests.missing", "Plugin not installed."
    )
    assert action == "skip"
    assert "skip_btn" in captured


def test_prompt_orphan_recovery_abort(qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)

    def fake_exec(self):
        for btn in self.buttons():
            if self.buttonRole(btn) == QMessageBox.ButtonRole.RejectRole:
                self.setProperty("_eggseis_clicked", btn)
                return 0
        return 0

    def fake_clicked_button(self):
        return self.property("_eggseis_clicked")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)

    action = win._prompt_orphan_recovery(
        "Missing horizon", "missing_horizon", "Horizon not in project."
    )
    assert action == "abort"
