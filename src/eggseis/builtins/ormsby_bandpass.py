"""Ormsby-style bandpass filter (zero-phase, FIR) applied per trace."""

from __future__ import annotations

import numpy as np
from scipy.signal import filtfilt, firwin

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="Ormsby Bandpass", version="0.1.0")
def ormsby_bandpass(
    trace: np.ndarray,
    context: dict,
    f_low_pass: float = Param(10.0, label="Low pass", min=0.5, max=500.0, units="Hz"),
    f_high_pass: float = Param(60.0, label="High pass", min=0.5, max=500.0, units="Hz"),
    n_taps: int = Param(101, label="Filter taps", min=11, max=501, step=2),
) -> np.ndarray:
    n_samples = trace.shape[-1]
    if n_samples < 4:
        return trace.astype(np.float32)

    fs = 1000.0 / float(context["sample_rate_ms"])
    nyq = fs / 2.0

    # Defensive band ordering (user can drag low past high).
    lo, hi = (f_low_pass, f_high_pass) if f_low_pass <= f_high_pass else (f_high_pass, f_low_pass)
    lo = float(np.clip(lo, 0.5, nyq * 0.99))
    hi = float(np.clip(hi, lo + 0.5, nyq * 0.999))
    if hi <= lo:
        return trace.astype(np.float32)

    # n_taps must be odd and small enough that filtfilt's padlen = 3*n - 1 < n_samples.
    max_taps = max(5, ((n_samples - 1) // 3) | 1)  # largest odd k with 3k - 1 < n
    n = int(min(int(n_taps), max_taps))
    if n % 2 == 0:
        n += 1
    if n < 5:
        return trace.astype(np.float32)

    taps = firwin(n, [lo, hi], pass_zero=False, fs=fs, window="hamming")
    padlen = min(3 * n - 1, n_samples - 1)
    return filtfilt(taps, 1.0, trace, padlen=padlen).astype(np.float32)
