"""Pytest fixtures shared across tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from eggseis.data import SurveyGeometry


class FakeBackend:
    """In-memory backend satisfying the SeismicBackend Protocol.

    Used to test SeismicVolume + Protocol contract without needing a real
    MDIO fixture. Geometry is fixed and reads return deterministic synthetic
    data so assertions can check exact values.
    """

    def __init__(
        self,
        inline_min: int = 100,
        inline_max: int = 109,
        xline_min: int = 300,
        xline_max: int = 314,
        n_samples: int = 32,
        sample_rate_ms: float = 4.0,
    ):
        self._geometry = SurveyGeometry(
            inline_min=inline_min,
            inline_max=inline_max,
            inline_step=1,
            xline_min=xline_min,
            xline_max=xline_max,
            xline_step=1,
            n_samples=n_samples,
            sample_rate_ms=sample_rate_ms,
        )
        rng = np.random.default_rng(seed=42)
        self._cube = rng.standard_normal(self._geometry.shape).astype(np.float32)

    @property
    def geometry(self) -> SurveyGeometry:
        return self._geometry

    @property
    def dtype(self) -> np.dtype:
        return self._cube.dtype

    def read_inline(self, inline: int) -> np.ndarray:
        i = (inline - self._geometry.inline_min) // self._geometry.inline_step
        return self._cube[i, :, :]

    def read_xline(self, xline: int) -> np.ndarray:
        x = (xline - self._geometry.xline_min) // self._geometry.xline_step
        return self._cube[:, x, :]

    def read_timeslice(self, sample_index: int) -> np.ndarray:
        return self._cube[:, :, sample_index]

    def read_trace(self, inline: int, xline: int) -> np.ndarray:
        i = (inline - self._geometry.inline_min) // self._geometry.inline_step
        x = (xline - self._geometry.xline_min) // self._geometry.xline_step
        return self._cube[i, x, :]

    @property
    def version(self) -> tuple:
        return ("fake", id(self))


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


def _build_synthetic_mdio(path: Path) -> None:
    import xarray as xr
    from mdio import to_mdio

    n_il, n_xl, n_t = 8, 6, 32
    inline = np.arange(100, 100 + n_il, dtype=np.int32)
    crossline = np.arange(300, 300 + n_xl, dtype=np.int32)
    time = np.arange(n_t, dtype=np.float32) * 4.0

    rng = np.random.default_rng(seed=1)
    data = rng.standard_normal((n_il, n_xl, n_t)).astype(np.float32)

    ds = xr.Dataset(
        data_vars={"amplitude": (("inline", "crossline", "time"), data)},
        coords={"inline": inline, "crossline": crossline, "time": time},
        attrs={"defaultVariableName": "amplitude"},
    )
    ds.coords["time"].attrs["units"] = "ms"
    to_mdio(ds, str(path), mode="w")


@pytest.fixture(scope="session")
def sample_mdio_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("mdio") / "synth.mdio"
    _build_synthetic_mdio(path)
    return path


@pytest.fixture(scope="session")
def demo_project_path(tmp_path_factory, sample_mdio_path) -> Path:
    """A demo project layout pointing at the synthetic MDIO fixture."""
    import shutil

    root = tmp_path_factory.mktemp("project")
    surveys = root / "surveys"
    surveys.mkdir()
    target = surveys / "synth.mdio"
    shutil.copytree(sample_mdio_path, target)
    (root / "project.yaml").write_text(
        "name: demo\n"
        "surveys:\n"
        "  - name: synth\n"
        "    path: surveys/synth.mdio\n"
        "horizons: []\n"
        "wells: []\n"
    )
    return root


@pytest.fixture
def linear_spec():
    """Deterministic trace * scalar. Vectorized batch path supported."""
    from eggseis.plugin import Param, clear_registry, trace_attribute

    clear_registry()

    @trace_attribute(name="Linear Scale", version="0.1.0", vectorized=True, deterministic=True)
    def linear(traces: np.ndarray, scale: float = Param(default=1.0)) -> np.ndarray:
        return traces * scale

    yield linear._eggseis_spec
    clear_registry()


@pytest.fixture
def make_pipeline():
    """Build a Pipeline from a list of (spec, params) tuples or bare specs."""
    def _make(*specs_and_params):
        from eggseis.pipeline.model import Node, Pipeline
        p = Pipeline()
        for entry in specs_and_params:
            if isinstance(entry, tuple):
                spec, params = entry
            else:
                spec = entry
                params = spec.param_model()
            p.append(Node(spec=spec, params=params))
        return p
    return _make


@pytest.fixture
def param_dock_factory():
    """Factory that builds a ParamDock per Node, seeded from the node's params."""
    def _factory(node):
        from eggseis.widgets.param_dock import ParamDock
        widget = ParamDock()
        widget.set_plugin(node.spec, params=node.params)
        return widget
    return _factory
