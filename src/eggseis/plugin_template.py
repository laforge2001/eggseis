"""Generate a starter plugin file and open it in the system editor."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from eggseis.plugin_loader import USER_PLUGIN_DIR

TEMPLATE = '''\
"""User plugin: {display}.

Each parameter must use a Param(...) default; the GUI builds sliders
automatically from the bounds. Restart eggseis to register changes.
"""

from __future__ import annotations

import numpy as np

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="{display}", version="0.1.0")
def {func}(
    trace: np.ndarray,
    gain: float = Param(1.0, label="Gain", min=0.0, max=10.0),
) -> np.ndarray:
    return (trace * gain).astype(np.float32)
'''


def _slugify(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    if not s:
        raise ValueError(f"could not derive a Python identifier from {name!r}")
    if s[0].isdigit():
        s = f"_{s}"
    return s


def create_template(name: str, target_dir: Path | None = None) -> Path:
    """Write a starter plugin file. Returns the resulting path.

    Raises FileExistsError if the target file already exists.
    """
    directory = target_dir if target_dir is not None else USER_PLUGIN_DIR
    directory.mkdir(parents=True, exist_ok=True)
    func = _slugify(name)
    target = directory / f"{func}.py"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(TEMPLATE.format(display=name, func=func))
    return target


def open_in_editor(path: Path) -> None:
    """Open `path` in the OS default editor. Best-effort, swallows errors."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass
