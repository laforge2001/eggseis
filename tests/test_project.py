"""Tests for the Project model."""

from __future__ import annotations

from pathlib import Path

import pytest

from eggseis.project import Project, SurveyEntry


def _write_project(root: Path, body: str) -> None:
    (root / "project.yaml").write_text(body)


def test_load_minimal_project(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        "name: T\n"
        "surveys:\n"
        "  - name: A\n"
        "    path: a.mdio\n"
        "horizons: []\n"
        "wells: []\n",
    )
    proj = Project.load(tmp_path)

    assert proj.name == "T"
    assert proj.root == tmp_path.resolve()
    assert proj.surveys == (
        SurveyEntry(name="A", path=(tmp_path / "a.mdio").resolve()),
    )


def test_load_resolves_relative_paths(tmp_path: Path) -> None:
    surveys_dir = tmp_path / "surveys"
    surveys_dir.mkdir()
    _write_project(
        tmp_path,
        "name: P\n"
        "surveys:\n"
        "  - name: S1\n"
        "    path: surveys/s1.mdio\n",
    )
    proj = Project.load(tmp_path)

    assert proj.surveys[0].path == (surveys_dir / "s1.mdio").resolve()


def test_load_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Project.load(tmp_path)


def test_load_missing_name(tmp_path: Path) -> None:
    _write_project(tmp_path, "surveys: []\n")
    with pytest.raises(ValueError, match="missing required key 'name'"):
        Project.load(tmp_path)


def test_load_no_surveys_key(tmp_path: Path) -> None:
    _write_project(tmp_path, "name: empty\n")
    proj = Project.load(tmp_path)
    assert proj.surveys == ()
