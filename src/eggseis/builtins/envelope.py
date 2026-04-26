"""Envelope (instantaneous amplitude) of each trace via the analytic signal."""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from eggseis.plugin import trace_attribute


@trace_attribute(name="Envelope", version="0.1.0")
def envelope(trace: np.ndarray) -> np.ndarray:
    return np.abs(hilbert(trace)).astype(np.float32)
