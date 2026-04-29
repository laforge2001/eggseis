"""Compute job + cancellation primitives. No Qt deps — pure Python."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import BaseModel

from eggseis.axes import Axis
from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec

_job_ids = itertools.count(1)


class CancellationToken:
    """Thread-safe one-way flag. Workers poll `.cancelled` between tile rows."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class Job:
    """One section-level compute request. Output buffer is owned by the job."""

    id: int = field(default_factory=lambda: next(_job_ids))
    spec: PluginSpec | None = None
    params: BaseModel | None = None
    volume: SeismicVolume | None = None
    axis: Axis = Axis.INLINE
    index: int = 0
    section: np.ndarray | None = None
    output: np.ndarray | None = None
    context: dict[str, Any] = field(default_factory=dict)
    token: CancellationToken = field(default_factory=CancellationToken)
    cache_key: Any = None  # CacheKey, set at dispatch; reused on finalize.
