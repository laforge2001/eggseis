"""Instantaneous frequency: time derivative of unwrapped instantaneous phase."""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from eggseis.plugin import trace_attribute


@trace_attribute(name="Instantaneous Frequency", version="0.1.0")
def instantaneous_frequency(trace: np.ndarray, context: dict) -> np.ndarray:
    fs = 1000.0 / float(context["sample_rate_ms"])
    phase = np.unwrap(np.angle(hilbert(trace)))
    freq = np.gradient(phase) * fs / (2.0 * np.pi)
    return freq.astype(np.float32)
