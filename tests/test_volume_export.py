"""Volume export — apply graph across every inline, write a new MDIO."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.backends.mdio import MDIOBackend
from eggseis.data import SeismicVolume
from eggseis.graph.model import SOURCE_ID, Edge, Graph, Node
from eggseis.plugin import clear_registry


@pytest.fixture(autouse=True)
def _clear():
    clear_registry()
    yield
    clear_registry()


def _node(spec, **kw) -> Node:
    return Node(spec=spec, params=spec.param_model(**kw))


def test_export_empty_graph_round_trips_raw(tmp_path, sample_mdio_path):
    from eggseis.graph.runner import export_volume_with_graph

    src_vol = SeismicVolume(MDIOBackend(sample_mdio_path))
    out_path = tmp_path / "exported.mdio"
    export_volume_with_graph(Graph(), src_vol, out_path)

    out_vol = SeismicVolume(MDIOBackend(out_path))
    assert out_vol.geometry.shape == src_vol.geometry.shape
    np.testing.assert_array_equal(
        out_vol.read_inline(src_vol.geometry.inline_min),
        src_vol.read_inline(src_vol.geometry.inline_min),
    )


def test_export_with_linear_node_applies_per_inline(
    tmp_path, sample_mdio_path, linear_spec
):
    from eggseis.graph.runner import export_volume_with_graph

    src_vol = SeismicVolume(MDIOBackend(sample_mdio_path))
    g = Graph()
    n = _node(linear_spec, scale=3.0)
    g.add_node(n)
    g.connect(Edge(SOURCE_ID, "inline", n.node_id, "traces"))
    g.set_tap(n.node_id)

    out_path = tmp_path / "scaled.mdio"
    export_volume_with_graph(g, src_vol, out_path)

    out_vol = SeismicVolume(MDIOBackend(out_path))
    assert out_vol.geometry.shape == src_vol.geometry.shape
    raw = src_vol.read_inline(src_vol.geometry.inline_min).astype(np.float32)
    got = out_vol.read_inline(src_vol.geometry.inline_min)
    np.testing.assert_allclose(got, raw * 3.0, atol=1e-5)


def test_export_progress_callback_fires_per_inline(tmp_path, sample_mdio_path):
    from eggseis.graph.runner import export_volume_with_graph

    src_vol = SeismicVolume(MDIOBackend(sample_mdio_path))
    n_il = src_vol.geometry.n_inlines

    seen: list[tuple[int, int]] = []
    export_volume_with_graph(
        Graph(),
        src_vol,
        tmp_path / "progress.mdio",
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert len(seen) == n_il
    assert seen[-1] == (n_il, n_il)
