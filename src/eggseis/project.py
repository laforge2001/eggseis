"""Project model: a plain directory with a project.yaml manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SurveyEntry:
    name: str
    path: Path


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    surveys: tuple[SurveyEntry, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, project_dir: str | Path) -> Project:
        root = Path(project_dir).resolve()
        manifest = root / "project.yaml"
        if not manifest.is_file():
            raise FileNotFoundError(f"No project.yaml in {root}")
        data = yaml.safe_load(manifest.read_text()) or {}

        if "name" not in data:
            raise ValueError(f"project.yaml missing required key 'name': {manifest}")

        surveys = tuple(
            SurveyEntry(name=s["name"], path=(root / s["path"]).resolve())
            for s in data.get("surveys", [])
        )
        return cls(name=data["name"], root=root, surveys=surveys)
