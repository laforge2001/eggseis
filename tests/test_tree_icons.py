"""apply_to_tree assigns category icons to root nodes only."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qtawesome")


def test_apply_to_tree_sets_icons_on_category_roots(qtbot):
    from eggseis.project import Project
    from eggseis.widgets.project_tree import ProjectTreeWidget
    from eggseis.widgets.tree_icons import apply_to_tree

    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    tree.set_project(Project(name="test", root="/tmp"))
    apply_to_tree(tree)

    project_root = tree.topLevelItem(0)
    surveys = project_root.child(0)
    horizons = project_root.child(1)
    wells = project_root.child(2)
    assert not surveys.icon(0).isNull()
    assert not horizons.icon(0).isNull()
    assert not wells.icon(0).isNull()


def test_apply_to_tree_does_not_set_per_item_icons(qtbot):
    """Per-item children get no icons (PaleoScan-aligned low chrome)."""
    from pathlib import Path

    from eggseis.project import Project
    from eggseis.widgets.project_tree import ProjectTreeWidget
    from eggseis.widgets.tree_icons import apply_to_tree

    tree = ProjectTreeWidget()
    qtbot.addWidget(tree)
    proj = Project.load(Path("examples/demo-project"))
    tree.set_project(proj)
    apply_to_tree(tree)

    project_root = tree.topLevelItem(0)
    surveys_root = project_root.child(0)
    if surveys_root.childCount() > 0:
        first_child = surveys_root.child(0)
        assert first_child.icon(0).isNull()
