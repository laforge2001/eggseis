"""Project model: a plain directory with a project.yaml manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as _replace
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
    graph: dict | None = None       # {"active_survey": str, "graph": Graph.to_dict()}
    viewer: dict | None = None      # {"axis", "index", "colormap", "levels_locked"}

    def with_graph(self, *, graph_dict: dict, active_survey: str) -> Project:
        return _replace(self, graph={"active_survey": active_survey, "graph": graph_dict})

    def with_viewer(self, viewer: dict) -> Project:
        return _replace(self, viewer=dict(viewer))

    def with_horizon_added(self, entry: HorizonEntry) -> Project:
        existing = tuple(h for h in self.horizons if h.name != entry.name)
        return _replace(self, horizons=(*existing, entry))

    def with_well_added(self, entry: WellEntry) -> Project:
        existing = tuple(w for w in self.wells if w.name != entry.name)
        return _replace(self, wells=(*existing, entry))

    def load_horizon(self, name: str):
        """Look up a HorizonEntry by name and return the loaded Horizon object.

        Raises KeyError if no entry matches.
        """
        from eggseis.data.horizon import Horizon

        entry = next((h for h in self.horizons if h.name == name), None)
        if entry is None:
            raise KeyError(f"horizon {name!r} not in project")
        return Horizon.load(entry.path)

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
            # Relative paths resolve against the project root, matching surveys.
            raw = Path(h["path"])
            resolved = raw if raw.is_absolute() else (root / raw)
            horizons.append(HorizonEntry(
                name=h["name"],
                path=resolved,
                color=h.get("color", "#ffcc00"),
            ))

        wells: list[WellEntry] = []
        for w in data.get("wells", []) or []:
            raw = Path(w["path"])
            resolved = raw if raw.is_absolute() else (root / raw)
            wells.append(WellEntry(name=w["name"], path=resolved))

        return cls(
            name=data["name"],
            root=root,
            surveys=tuple(surveys),
            horizons=tuple(horizons),
            wells=tuple(wells),
            schema_version=schema_version,
            graph=data.get("graph"),
            viewer=data.get("viewer"),
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
                {"name": h.name, "path": _rel_or_abs(h.path, self.root), "color": h.color}
                for h in self.horizons
            ]
        if self.wells:
            out["wells"] = [
                {"name": w.name, "path": _rel_or_abs(w.path, self.root)}
                for w in self.wells
            ]
        if self.graph is not None:
            out["graph"] = self.graph
        if self.viewer is not None:
            out["viewer"] = self.viewer
        manifest.write_text(yaml.safe_dump(out, sort_keys=False))
