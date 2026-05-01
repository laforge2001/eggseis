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
