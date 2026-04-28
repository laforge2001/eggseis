"""Instantaneous phase from the analytic signal, in radians."""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from eggseis.plugin import trace_attribute


@trace_attribute(name="Instantaneous Phase", version="0.1.0")
def instantaneous_phase(trace: np.ndarray) -> np.ndarray:
    return np.angle(hilbert(trace)).astype(np.float32)
