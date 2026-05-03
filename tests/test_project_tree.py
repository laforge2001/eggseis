"""ProjectTreeWidget — labels, double-click routing, right-click load menu."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from eggseis.project import HorizonEntry, Project, SurveyEntry, WellEntry
from eggseis.widgets.project_tree import ProjectTreeWidget


def _make_project(tmp_path: Path) -> Project:
    survey_dir = tmp_path / "s.mdio"
    survey_dir.mkdir()
    horizon_dir = tmp_path / "horizons" / "top"
    horizon_dir.mkdir(parents=True)
    well_path = tmp_path / "wells" / "w1.h5"
    well_path.parent.mkdir()
    well_path.touch()
    return Project(
        name="P",
        root=tmp_path.resolve(),
        surveys=(SurveyEntry(name="S1", path=survey_dir.resolve()),),
        horizons=(HorizonEntry(name="top", path=horizon_dir.resolve()),),
        wells=(WellEntry(name="w1", path=well_path.resolve()),),
    )


def _category_items(tree: ProjectTreeWidget) -> dict[str, object]:
    """Return a dict keyed by category label ('Surveys', 'Horizons', 'Wells')."""
    root = tree.topLevelItem(0)
    return {root.child(i).text(0): root.child(i) for i in range(root.childCount())}


def test_category_labels_have_no_counts(qtbot, tmp_path: Path) -> None:
    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(_make_project(tmp_path))
    cats = _category_items(tree)
    assert "Surveys" in cats
    assert "Horizons" in cats
    assert "Wells" in cats
    # Sanity: the old "Horizons (N)" / "Wells (N)" labels are gone.
    for label in cats:
        assert "(" not in label, f"unexpected count in label: {label!r}"


def test_double_click_horizon_emits_horizon_activated(qtbot, tmp_path: Path) -> None:
    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(_make_project(tmp_path))
    horizons_node = _category_items(tree)["Horizons"]
    horizon_item = horizons_node.child(0)

    received: list[str] = []
    tree.horizonActivated.connect(received.append)
    tree.itemDoubleClicked.emit(horizon_item, 0)
    assert received == ["top"]


def test_double_click_survey_still_emits_survey_activated(qtbot, tmp_path: Path) -> None:
    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(_make_project(tmp_path))
    surveys_node = _category_items(tree)["Surveys"]
    survey_item = surveys_node.child(0)

    received: list[Path] = []
    tree.surveyActivated.connect(received.append)
    tree.itemDoubleClicked.emit(survey_item, 0)
    assert len(received) == 1
    assert received[0].name == "s.mdio"


def test_context_menu_emits_load_requested_for_categories(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Stub QMenu.exec_ + monkeypatch the action triggered to capture intent."""
    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(_make_project(tmp_path))
    cats = _category_items(tree)

    captured: list[str] = []
    tree.loadRequested.connect(captured.append)

    # Capture the QMenu actions that _on_context_menu builds without
    # spinning a real exec_ loop.
    from PySide6.QtWidgets import QMenu

    actions_seen: list[list[str]] = []

    def fake_exec_(self, _global_pos):
        labels = [a.text() for a in self.actions()]
        actions_seen.append(labels)
        for a in self.actions():
            if a.text().startswith("Load"):
                a.trigger()

    monkeypatch.setattr(QMenu, "exec_", fake_exec_)

    # Trigger context menus on each category by feeding the category item's
    # rect center as the position.
    for label in ("Surveys", "Horizons", "Wells"):
        item = cats[label]
        rect = tree.visualItemRect(item)
        if rect.isNull():
            tree.expandAll()
            rect = tree.visualItemRect(item)
        tree._on_context_menu(rect.center())

    assert captured == ["survey", "horizon", "well"]
    # Each menu showed a "Load…" action.
    for labels in actions_seen:
        assert any(t.startswith("Load") for t in labels)


def test_context_menu_on_non_category_item_is_noop(qtbot, tmp_path: Path) -> None:
    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(_make_project(tmp_path))
    surveys_node = _category_items(tree)["Surveys"]
    survey_item = surveys_node.child(0)

    captured: list[str] = []
    tree.loadRequested.connect(captured.append)

    rect = tree.visualItemRect(survey_item)
    tree._on_context_menu(rect.center())
    assert captured == []
