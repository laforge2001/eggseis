# M1 — "The data opens"

**Milestone 1 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and the milestones that follow.**

---

## Goal

Build a CLI that opens an MDIO survey, prints geometry, reads an inline, and saves it as a PNG. No UI yet.

The point of M1 is to **prove you can read seismic data through a clean abstraction.** Not to build a full data layer. Not to optimize. Not to handle every edge case. Just to read an MDIO survey, expose it through a `SeismicVolume` object, and prove the whole stack works end-to-end with a CLI.

Stay disciplined about that scope and M1 is a couple of focused weekends. Let it sprawl into "build the perfect data layer" and it'll take six months.

## Exit criteria

You're done with M1 when this works:

```bash
$ eggseis info tests/data/sample.mdio
Survey: F3 Netherlands (sample fragment)
  Inline range: 100–200
  Crossline range: 300–400
  Samples: 462
  Sample rate: 4 ms
  Format: float32

$ eggseis dump-inline tests/data/sample.mdio 150 --output inline_150.png
Wrote inline_150.png (1024×462, 0.4 MB)
```

And tests pass on Linux, macOS, and Windows in CI.

---

## Step 1: Project structure

In your fresh `eggseis` repo, create this layout:

```
eggseis/
├── README.md                 # already there
├── LICENSE                   # already there
├── ROADMAP.md                # already there
├── .gitignore                # already there
├── pyproject.toml            # NEW — replace any placeholder version
├── src/
│   └── eggseis/
│       ├── __init__.py
│       ├── data.py           # SeismicVolume abstraction
│       ├── backends/
│       │   ├── __init__.py
│       │   └── mdio.py       # MDIOBackend implementation
│       └── cli.py            # CLI entry point
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # pytest fixtures
│   ├── test_data.py
│   ├── test_mdio_backend.py
│   └── data/                 # small test surveys (gitignored if large)
└── .github/
    └── workflows/
        └── tests.yml         # CI on Linux/macOS/Windows
```

The `src/` layout (vs. having `eggseis/` at the top level) is the modern Python convention and prevents a class of import bugs. Use it.

## Step 2: Set up the Python environment

Pick a dev environment approach. Three reasonable options:

- **Conda** — matches what eggseis will distribute as. Most consistent with the long-term plan. Recommended.
- **venv + pip** — simpler if you already have Python installed.
- **uv** — newer, much faster, increasingly popular.

For conda:

```bash
conda create -n eggseis python=3.12 -c conda-forge
conda activate eggseis
conda install -c conda-forge mdio numpy pytest typer rich pillow
pip install -e ".[dev]"
```

The `-e ".[dev]"` installs your package in "editable" mode — changes to your source code take effect immediately without reinstalling. This is the only way to develop a Python package sanely.

## Step 3: pyproject.toml

This is the source of truth for dependencies, version, and entry points.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "eggseis"
version = "0.1.0.dev0"
description = "An open-source desktop application for viewing and analyzing seismic data, with a Python plugin system."
readme = "README.md"
requires-python = ">=3.10"
license = "Apache-2.0"
license-files = ["LICENSE"]
authors = [{ name = "Eric [Surname]", email = "your-email@example.com" }]
keywords = ["seismic", "geoscience", "geophysics", "interpretation", "segy", "mdio"]
classifiers = [
    "Development Status :: 2 - Pre-Alpha",
    "Intended Audience :: Science/Research",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering",
    "Topic :: Scientific/Engineering :: Visualization",
]

dependencies = [
    "numpy>=1.24",
    "mdio>=0.8",
    "typer>=0.12",
    "rich>=13.0",
    "pillow>=10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.10",
]

[project.scripts]
eggseis = "eggseis.cli:app"

[project.urls]
Homepage = "https://github.com/eggseis/eggseis"
Repository = "https://github.com/eggseis/eggseis"
Issues = "https://github.com/eggseis/eggseis/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/eggseis"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "RUF"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers"
```

`version = "0.1.0.dev0"` — the `.dev0` suffix marks this as pre-release, appropriate for M1 work and won't conflict with your placeholder `0.0.2`.

## Step 4: data.py — the SeismicVolume abstraction

This is the heart of M1. The `SeismicVolume` is the stable public API everything upstream depends on. Get it right and you build for years on top of it.

```python
# src/eggseis/data.py
"""Domain model for seismic data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class SurveyGeometry:
    """Geometric description of a 3D seismic survey."""

    inline_min: int
    inline_max: int
    inline_step: int
    xline_min: int
    xline_max: int
    xline_step: int
    n_samples: int
    sample_rate_ms: float  # time sample interval in ms

    @property
    def n_inlines(self) -> int:
        return (self.inline_max - self.inline_min) // self.inline_step + 1

    @property
    def n_xlines(self) -> int:
        return (self.xline_max - self.xline_min) // self.xline_step + 1

    @property
    def shape(self) -> tuple[int, int, int]:
        """(n_inlines, n_xlines, n_samples)"""
        return (self.n_inlines, self.n_xlines, self.n_samples)

    @property
    def time_max_ms(self) -> float:
        return (self.n_samples - 1) * self.sample_rate_ms


@runtime_checkable
class SeismicBackend(Protocol):
    """Storage backend interface — what every backend must implement."""

    @property
    def geometry(self) -> SurveyGeometry: ...

    @property
    def dtype(self) -> np.dtype: ...

    def read_inline(self, inline: int) -> np.ndarray: ...
    def read_xline(self, xline: int) -> np.ndarray: ...
    def read_timeslice(self, sample_index: int) -> np.ndarray: ...
    def read_trace(self, inline: int, xline: int) -> np.ndarray: ...


class SeismicVolume:
    """The stable public abstraction for a 3D seismic volume.

    Plugins, viewers, and CLI commands talk to this — never to backends
    directly. Swapping the backend (MDIO, OpenVDS, TileDB) leaves the
    upstream code untouched.
    """

    def __init__(self, backend: SeismicBackend, name: str = "unnamed"):
        self._backend = backend
        self.name = name

    @property
    def geometry(self) -> SurveyGeometry:
        return self._backend.geometry

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.geometry.shape

    @property
    def dtype(self) -> np.dtype:
        return self._backend.dtype

    def read_inline(self, inline: int) -> np.ndarray:
        """Read a single inline as shape (n_xlines, n_samples)."""
        return self._backend.read_inline(inline)

    def read_xline(self, xline: int) -> np.ndarray:
        """Read a single crossline as shape (n_inlines, n_samples)."""
        return self._backend.read_xline(xline)

    def read_timeslice(self, sample_index: int) -> np.ndarray:
        """Read a single time slice as shape (n_inlines, n_xlines)."""
        return self._backend.read_timeslice(sample_index)

    def read_trace(self, inline: int, xline: int) -> np.ndarray:
        """Read a single trace as shape (n_samples,)."""
        return self._backend.read_trace(inline, xline)

    def __repr__(self) -> str:
        g = self.geometry
        return (
            f"SeismicVolume(name={self.name!r}, "
            f"shape={g.shape}, dtype={self.dtype}, "
            f"sample_rate={g.sample_rate_ms}ms)"
        )
```

**Two design notes worth internalizing:**

The `Protocol` for `SeismicBackend` is doing real work — it's a structural contract. Anything with those four read methods and the geometry/dtype properties counts as a backend, no inheritance required. Swapping in a synthetic backend for testing or a different storage format requires zero ceremony.

`SurveyGeometry` is a frozen dataclass on purpose. It's hashable, immutable, and makes a clean cache key once you get to M4. Frozen-by-default is the right discipline for value objects.

## Step 5: backends/mdio.py — the MDIO backend

The only backend in M1. Probably 50–80 lines depending on edge cases.

**This sketch is approximate.** Verify the actual MDIO API before implementing — the TGS team has been actively iterating. Consult https://mdio-python.readthedocs.io for current method names and access patterns.

```python
# src/eggseis/backends/mdio.py
"""MDIO storage backend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from mdio import MDIOReader  # confirm exact import path

from eggseis.data import SurveyGeometry


class MDIOBackend:
    """Read 3D seismic from an MDIO store."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._reader = MDIOReader(str(self.path))
        self._geometry = self._build_geometry()

    def _build_geometry(self) -> SurveyGeometry:
        # Fill in based on MDIO's actual API
        # — typically reading from self._reader.grid or similar
        ...

    @property
    def geometry(self) -> SurveyGeometry:
        return self._geometry

    @property
    def dtype(self) -> np.dtype:
        return self._reader.stats["sample_format"]  # check actual API

    def read_inline(self, inline: int) -> np.ndarray:
        idx = (inline - self._geometry.inline_min) // self._geometry.inline_step
        return self._reader[idx, :, :]

    def read_xline(self, xline: int) -> np.ndarray:
        idx = (xline - self._geometry.xline_min) // self._geometry.xline_step
        return self._reader[:, idx, :]

    def read_timeslice(self, sample_index: int) -> np.ndarray:
        return self._reader[:, :, sample_index]

    def read_trace(self, inline: int, xline: int) -> np.ndarray:
        il = (inline - self._geometry.inline_min) // self._geometry.inline_step
        xl = (xline - self._geometry.xline_min) // self._geometry.xline_step
        return self._reader[il, xl, :]
```

**Pragmatic approach:** install mdio, point it at a sample dataset, get a NumPy array out of it, then refactor the working code into the structure above. Don't write the abstraction first and discover it doesn't fit — write the spike, then refactor.

## Step 6: cli.py — the command-line interface

```python
# src/eggseis/cli.py
"""Command-line interface for eggseis."""

from pathlib import Path

import numpy as np
import typer
from rich.console import Console
from rich.table import Table

from eggseis.backends.mdio import MDIOBackend
from eggseis.data import SeismicVolume

app = typer.Typer(help="eggseis — open-source seismic interpretation")
console = Console()


@app.command()
def info(survey: Path = typer.Argument(..., help="Path to MDIO survey")) -> None:
    """Show summary information about a seismic survey."""
    backend = MDIOBackend(survey)
    volume = SeismicVolume(backend, name=survey.stem)
    g = volume.geometry

    table = Table(title=f"Survey: {volume.name}", show_header=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Inline range", f"{g.inline_min}–{g.inline_max} (step {g.inline_step})")
    table.add_row("Xline range", f"{g.xline_min}–{g.xline_max} (step {g.xline_step})")
    table.add_row("Samples", str(g.n_samples))
    table.add_row("Sample rate", f"{g.sample_rate_ms} ms")
    table.add_row("Time max", f"{g.time_max_ms:.1f} ms")
    table.add_row("Shape", f"{g.shape}")
    table.add_row("Dtype", str(volume.dtype))
    console.print(table)


@app.command("dump-inline")
def dump_inline(
    survey: Path = typer.Argument(..., help="Path to MDIO survey"),
    inline: int = typer.Argument(..., help="Inline number"),
    output: Path = typer.Option("inline.png", "--output", "-o", help="Output PNG path"),
) -> None:
    """Read an inline and save it as a PNG."""
    from PIL import Image

    backend = MDIOBackend(survey)
    volume = SeismicVolume(backend, name=survey.stem)
    data = volume.read_inline(inline)

    # Normalize to 0-255 with a 1-99 percentile linear stretch
    arr = data.T  # transpose so time is vertical
    p_low, p_high = np.percentile(arr, [1, 99])
    arr = np.clip((arr - p_low) / (p_high - p_low), 0, 1)
    arr_u8 = (arr * 255).astype(np.uint8)

    Image.fromarray(arr_u8).save(output)
    console.print(f"[green]Wrote[/green] {output} ({arr.shape[1]}×{arr.shape[0]})")


if __name__ == "__main__":
    app()
```

Once `pyproject.toml` is in place and `pip install -e ".[dev]"` has run, the `eggseis` command is available globally in your env.

## Step 7: Tests

Tests are not optional, even at M1. They're how you'll know in M3 that a refactor didn't break anything.

```python
# tests/conftest.py
"""Pytest fixtures shared across tests."""

import pytest


@pytest.fixture
def sample_mdio_path(tmp_path):
    """Path to a small synthetic MDIO survey for testing.

    In M1, generate a tiny synthetic survey programmatically using MDIO's
    writer, OR check in a small (<10 MB) test fixture. In later milestones
    this can become a downloaded F3 fragment.
    """
    ...
```

```python
# tests/test_data.py
"""Tests for the SeismicVolume abstraction."""

from eggseis.data import SurveyGeometry


def test_geometry_shape():
    g = SurveyGeometry(
        inline_min=100, inline_max=199, inline_step=1,
        xline_min=300, xline_max=399, xline_step=1,
        n_samples=512, sample_rate_ms=4.0,
    )
    assert g.n_inlines == 100
    assert g.n_xlines == 100
    assert g.shape == (100, 100, 512)
    assert g.time_max_ms == 511 * 4.0
```

Don't worry about test coverage in M1. Worry about **the smallest set of tests that would catch a real regression.** Geometry calculations, basic backend reads, CLI exit codes. That's enough.

## Step 8: CI

A minimal GitHub Actions workflow that runs tests on Linux, macOS, and Windows:

```yaml
# .github/workflows/tests.yml
name: tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest
      - run: ruff check .
```

Drop this in and CI runs on every push. If it goes red, fix it before doing anything else — green main is a discipline that pays back tenfold once you have collaborators.

---

## Execution order

In order, the smallest unit of progress that gets you started:

1. **Create the directory structure.** `mkdir -p src/eggseis/backends tests/data .github/workflows`. Touch the `__init__.py` files.

2. **Drop in the `pyproject.toml`** above. Edit name and email.

3. **Set up your conda environment.** `conda create`, activate, `pip install -e ".[dev]"`. Confirm `eggseis --help` works (typer's auto-generated help with no commands yet — that's fine).

4. **Find a sample MDIO file.** First real obstacle. MDIO's GitHub has examples; you may need to convert a small SEG-Y to MDIO using their CLI. The SEG Wiki F3 dataset is the standard test fixture in this space and is freely available. Even a tiny 50 MB fragment is plenty for M1.

5. **Write a one-file spike** that just opens the MDIO and prints the shape. Throwaway code — get the API right before structuring it. Put it in a notebook or a `scratch.py` file outside the package.

6. **Once the spike works, refactor it into `MDIOBackend`** following the structure above.

7. **Wire up the CLI** so `eggseis info path/to/survey.mdio` runs.

8. **Add the PNG dump command.** When `eggseis dump-inline survey.mdio 100 --output inline_100.png` produces a recognizable seismic image, **M1 is functionally complete.**

9. **Write the tests.** Push to GitHub. Watch CI go green.

Two focused weekends, maybe three. Don't let any single step block you for more than a few hours — if the MDIO API is fighting you, drop into the Software Underground `#mdio` Slack channel and ask.

---

## Tactical notes

**The hardest part of M1 won't be the code — it'll be MDIO itself.** Their library has been iterating, and the docs sometimes lag. Budget time for:

- Reading MDIO's actual current API
- Asking in the Software Underground `#mdio` Slack channel if you hit a wall
- Possibly converting a small SEG-Y to MDIO yourself using their tooling

**Legitimate fallback for M1 only:** if MDIO blocks you for more than a few sessions, swap in a `segyio`-based backend that reads directly from a small SEG-Y file. Same `SeismicBackend` Protocol, different storage. This is exactly what the abstraction is for. Move to MDIO at the start of M2.

**Spike before structure.** Don't write the abstraction layer first and discover MDIO doesn't fit it. Get a working call chain end to end (`mdio` → `numpy` → `Image.save`) in a single throwaway script, then refactor it into the layered structure. The abstraction emerges from working code; it doesn't precede it.

**Commit often, with messages from you.** Let Claude Code write the code; you write the commit messages. Summarizing changes in your own words is how you stay in command of the codebase.

**Push back when something feels off.** If Claude Code proposes an approach that contradicts a decision in `ROADMAP.md` (xarray as the data model, disk caching in M1, etc.), say no and point at the relevant section.

---

## When M1 is done

A clean exit from M1 looks like:

- `eggseis info` and `eggseis dump-inline` work on a real MDIO survey.
- All tests pass on Linux, macOS, and Windows in CI.
- The repo is pushed, the README is up to date, the `CHANGELOG.md` records "M1 complete."
- You commit and tag `v0.1.0a1` (alpha 1) on GitHub. Don't push to PyPI yet.
- Take a beat. Then start M2 — "The section appears."
