"""Sink plugin: write the section passing through to a .npy file.

Drop this node into the graph at any point and tap it (or anything
downstream) — every time the executor resolves it, the input section
is written to the configured path. The node passes its input through
unchanged so wiring continues normally.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from eggseis.plugin import Param, graph_node


@graph_node(
    name="Save Section (.npy)",
    version="0.1.0",
    inputs=("trace",),
    kind="sink",
    deterministic=False,  # Side-effect — never cached.
)
def save_section_npy(
    trace: np.ndarray,
    path: str = Param(default="section.npy", label="Output path"),
    context: dict | None = None,
) -> np.ndarray:
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, trace)
    return trace
