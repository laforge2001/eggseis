"""Project save/load round-trips graph + viewer state + horizons."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from eggseis.data.horizon import Horizon
from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import clear_registry


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


def _project_with_horizon(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "horizons" / "top").mkdir(parents=True)
    grid = np.full((4, 4), 50.0, dtype=np.float32)
    h = Horizon(name="top", grid=grid, geometry_ref="x")
    h.save(root / "horizons" / "top")
    (root / "project.yaml").write_text(
        "schema_version: 1\n"
        "name: test\n"
        "surveys: []\n"
        "horizons:\n"
        "  - {name: top, path: horizons/top, color: '#ffcc00'}\n"
    )
    return root


def test_save_round_trips_graph(tmp_path, linear_spec):
    """Project.graph carries M6 Graph.to_dict; save + reload preserves nodes + edges."""
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    graph = Graph()
    n = Node(spec=linear_spec, params=linear_spec.param_model(scale=2.0))
    graph.add_node(n)
    graph.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    graph.set_tap(n.node_id)

    p = Project.load(root)
    p_with_graph = p.with_graph(graph_dict=graph.to_dict(), active_survey="demo")
    p_with_graph.save()

    text = (root / "project.yaml").read_text()
    assert "graph:" in text

    reloaded = Project.load(root)
    assert reloaded.graph is not None
    assert reloaded.graph["active_survey"] == "demo"
    assert "graph" in reloaded.graph
    assert len(reloaded.graph["graph"]["nodes"]) == 1


def test_save_round_trips_viewer_state(tmp_path):
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    p2 = p.with_viewer(
        {"axis": "xline", "index": 305, "colormap": "seismic", "levels_locked": False}
    )
    p2.save()

    reloaded = Project.load(root)
    assert reloaded.viewer == {
        "axis": "xline", "index": 305, "colormap": "seismic", "levels_locked": False,
    }


def test_with_graph_returns_new_project(tmp_path):
    """Project is frozen — with_graph yields a new instance, original unchanged."""
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    empty = {"nodes": [], "edges": [], "tap_port": ["source", "inline"]}
    new = p.with_graph(graph_dict=empty, active_survey="demo")
    assert new is not p
    assert p.graph is None
    assert new.graph is not None


def test_default_graph_and_viewer_are_none(tmp_path):
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    assert p.graph is None
    assert p.viewer is None


def test_save_load_preserves_horizons(tmp_path):
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    p.save()
    reloaded = Project.load(root)
    assert len(reloaded.horizons) == 1
    assert reloaded.horizons[0].name == "top"


def test_project_load_horizon_returns_horizon_object(tmp_path):
    from eggseis.data.horizon import Horizon
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    h = p.load_horizon("top")
    assert isinstance(h, Horizon)
    assert h.name == "top"


def test_project_load_horizon_unknown_raises(tmp_path):
    from eggseis.project import Project

    root = _project_with_horizon(tmp_path)
    p = Project.load(root)
    with pytest.raises(KeyError, match="missing"):
        p.load_horizon("missing")


def test_project_load_well_returns_well_object(tmp_path):
    """Project.load_well mirrors load_horizon — returns a Well object."""
    from eggseis.data.well import Well
    from eggseis.project import Project

    root = tmp_path / "proj"
    root.mkdir()
    (root / "wells").mkdir()
    md = np.array([0.0, 100.0, 200.0], dtype=np.float32)
    deviation = np.column_stack([md, np.zeros_like(md), np.zeros_like(md)]).astype(np.float32)
    well = Well(name="W1", deviation=deviation, logs={}, markers=[], surface_xy=(0.0, 0.0))
    well.save(root / "wells" / "W1.h5")
    (root / "project.yaml").write_text(
        "schema_version: 1\n"
        "name: test\n"
        "surveys: []\n"
        "wells:\n"
        "  - {name: W1, path: wells/W1.h5}\n"
    )
    p = Project.load(root)
    loaded = p.load_well("W1")
    assert isinstance(loaded, Well)
    assert loaded.name == "W1"


def test_project_load_well_unknown_raises(tmp_path):
    from eggseis.project import Project

    root = tmp_path / "proj"
    root.mkdir()
    (root / "project.yaml").write_text(
        "schema_version: 1\nname: test\nsurveys: []\n"
    )
    p = Project.load(root)
    with pytest.raises(KeyError, match="missing"):
        p.load_well("missing")
