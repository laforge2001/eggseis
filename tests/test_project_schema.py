"""M7 schema versioning for project.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from eggseis.project import KNOWN_SCHEMA_VERSION, Project, SchemaVersionError


def _write_project(root: Path, manifest: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yaml").write_text(manifest)


def test_known_schema_version_is_one():
    assert KNOWN_SCHEMA_VERSION == 1


def test_load_v0_manifest_treats_missing_field_as_zero(tmp_path):
    """M2-M6 manifests have no schema_version. Loader treats missing as 0
    and either migrates or accepts as a known older version."""
    _write_project(tmp_path, "name: legacy\nsurveys: []\n")
    p = Project.load(tmp_path)
    assert p.schema_version == 0


def test_load_v1_manifest_carries_version(tmp_path):
    _write_project(tmp_path, "schema_version: 1\nname: current\nsurveys: []\n")
    p = Project.load(tmp_path)
    assert p.schema_version == 1


def test_load_future_version_raises(tmp_path):
    _write_project(tmp_path, "schema_version: 99\nname: future\nsurveys: []\n")
    with pytest.raises(SchemaVersionError, match="99"):
        Project.load(tmp_path)


def test_load_v1_manifest_with_horizons_and_wells(tmp_path):
    """Reading v1 manifest with horizons + wells lists yields the lists."""
    _write_project(
        tmp_path,
        (
            "schema_version: 1\n"
            "name: with extras\n"
            "surveys: []\n"
            "horizons:\n"
            "  - name: top\n"
            "    path: horizons/top\n"
            "    color: '#ffcc00'\n"
            "wells:\n"
            "  - name: well1\n"
            "    path: wells/well1.h5\n"
        ),
    )
    p = Project.load(tmp_path)
    assert len(p.horizons) == 1
    assert p.horizons[0].name == "top"
    assert p.horizons[0].color == "#ffcc00"
    assert len(p.wells) == 1
    assert p.wells[0].name == "well1"


def test_default_horizons_and_wells_lists_empty(tmp_path):
    _write_project(tmp_path, "name: empty\nsurveys: []\n")
    p = Project.load(tmp_path)
    assert p.horizons == ()
    assert p.wells == ()


def test_save_writes_schema_version_one(tmp_path):
    """A round-trip save bumps the manifest to v1 even if loaded as v0."""
    _write_project(tmp_path, "name: legacy\nsurveys: []\n")
    p = Project.load(tmp_path)
    p.save()
    text = (tmp_path / "project.yaml").read_text()
    assert "schema_version: 1" in text


def test_save_preserves_horizons_and_wells(tmp_path):
    _write_project(
        tmp_path,
        (
            "schema_version: 1\nname: x\nsurveys: []\n"
            "horizons:\n  - {name: a, path: horizons/a, color: '#ff0000'}\n"
            "wells:\n  - {name: w1, path: wells/w1.h5}\n"
        ),
    )
    p = Project.load(tmp_path)
    p.save()
    reloaded = Project.load(tmp_path)
    assert reloaded.horizons[0].name == "a"
    assert reloaded.wells[0].name == "w1"
