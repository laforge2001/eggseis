"""Project model: a plain directory with a project.yaml manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

KNOWN_SCHEMA_VERSION = 1


def _rel_or_abs(p: Path, root: Path) -> str:
    """Return path relative to root if possible, else absolute string."""
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


class SchemaVersionError(ValueError):
    """Manifest declares a schema version newer than this code understands."""


@dataclass(frozen=True)
class SurveyEntry:
    name: str
    path: Path


@dataclass(frozen=True)
class HorizonEntry:
    name: str
    path: Path
    color: str = "#ffcc00"


@dataclass(frozen=True)
class WellEntry:
    name: str
    path: Path


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    surveys: tuple[SurveyEntry, ...] = field(default_factory=tuple)
    horizons: tuple[HorizonEntry, ...] = field(default_factory=tuple)
    wells: tuple[WellEntry, ...] = field(default_factory=tuple)
    schema_version: int = 0

    @classmethod
    def load(cls, project_dir: str | Path) -> Project:
        root = Path(project_dir).resolve()
        manifest = root / "project.yaml"
        if not manifest.is_file():
            raise FileNotFoundError(f"No project.yaml in {root}")
        data = yaml.safe_load(manifest.read_text()) or {}

        schema_version = int(data.get("schema_version", 0))
        if schema_version > KNOWN_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"project.yaml schema_version={schema_version} is newer than "
                f"this build supports (max {KNOWN_SCHEMA_VERSION})"
            )

        if "name" not in data:
            raise ValueError(f"project.yaml missing required key 'name': {manifest}")

        surveys: list[SurveyEntry] = []
        for s in data.get("surveys", []):
            if "name" not in s:
                raise ValueError(f"survey entry missing 'name': {s}")
            if "path" not in s:
                raise ValueError(f"survey entry missing 'path': {s}")
            survey_path = (root / s["path"]).resolve()
            if not survey_path.exists():
                raise FileNotFoundError(
                    f"survey {s['name']!r} path does not exist: {survey_path}"
                )
            surveys.append(SurveyEntry(name=s["name"], path=survey_path))

        horizons: list[HorizonEntry] = []
        for h in data.get("horizons", []) or []:
            horizons.append(HorizonEntry(
                name=h["name"],
                path=Path(h["path"]),
                color=h.get("color", "#ffcc00"),
            ))

        wells: list[WellEntry] = []
        for w in data.get("wells", []) or []:
            wells.append(WellEntry(name=w["name"], path=Path(w["path"])))

        return cls(
            name=data["name"],
            root=root,
            surveys=tuple(surveys),
            horizons=tuple(horizons),
            wells=tuple(wells),
            schema_version=schema_version,
        )

    def save(self, path: Path | None = None) -> None:
        """Write the project.yaml manifest. Bumps to KNOWN_SCHEMA_VERSION."""
        manifest = (path if path is not None else self.root / "project.yaml")
        out: dict = {
            "schema_version": KNOWN_SCHEMA_VERSION,
            "name": self.name,
            "surveys": [
                {"name": s.name, "path": _rel_or_abs(s.path, self.root)}
                for s in self.surveys
            ],
        }
        if self.horizons:
            out["horizons"] = [
                {"name": h.name, "path": str(h.path), "color": h.color}
                for h in self.horizons
            ]
        if self.wells:
            out["wells"] = [
                {"name": w.name, "path": str(w.path)}
                for w in self.wells
            ]
        manifest.write_text(yaml.safe_dump(out, sort_keys=False))
