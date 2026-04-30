"""Subtract one section from another. First multi-input builtin in M6."""

from __future__ import annotations

import numpy as np

from eggseis.plugin import graph_node


@graph_node(name="Subtract", version="0.1.0", inputs=("a", "b"))
def subtract(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a - b
