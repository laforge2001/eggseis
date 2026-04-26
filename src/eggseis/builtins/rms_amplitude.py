"""RMS amplitude in a sliding window centered on each sample."""

from __future__ import annotations

import numpy as np

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="RMS Amplitude", version="0.1.0")
def rms_amplitude(
    trace: np.ndarray,
    window: int = Param(21, label="Window length", min=3, max=501, step=2),
) -> np.ndarray:
    w = int(window)
    if w < 1:
        w = 1
    if w % 2 == 0:
        w += 1
    sq = trace.astype(np.float64) ** 2
    kernel = np.ones(w, dtype=np.float64) / w
    smoothed = np.convolve(sq, kernel, mode="same")
    return np.sqrt(smoothed).astype(np.float32)
