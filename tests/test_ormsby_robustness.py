"""Stress-test Ormsby Bandpass for slider edge cases."""

from __future__ import annotations

import numpy as np
import pytest

from eggseis.builtins.ormsby_bandpass import ormsby_bandpass


def _trace(n: int = 32) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.standard_normal(n).astype(np.float32)


@pytest.mark.parametrize("f_low_pass,f_high_pass,n_taps,n_samples,sample_rate_ms", [
    (10.0, 60.0, 101, 32, 4.0),       # default params, short trace → likely fails (padlen)
    (10.0, 60.0, 11, 32, 4.0),        # short filter, short trace
    (10.0, 60.0, 501, 32, 4.0),       # max taps, short trace
    (300.0, 60.0, 101, 32, 4.0),      # f_low > f_high (slider crossover)
    (60.0, 10.0, 101, 32, 4.0),       # f_low > f_high explicit
    (200.0, 200.0, 101, 32, 4.0),     # both above nyquist
    (0.5, 500.0, 101, 32, 4.0),       # full band
    (10.0, 60.0, 101, 500, 4.0),      # plenty of samples
])
def test_ormsby_does_not_raise(f_low_pass, f_high_pass, n_taps, n_samples, sample_rate_ms):
    out = ormsby_bandpass(
        _trace(n_samples),
        context={"sample_rate_ms": sample_rate_ms},
        f_low_pass=f_low_pass,
        f_high_pass=f_high_pass,
        n_taps=n_taps,
    )
    assert out.shape == (n_samples,)
    assert np.isfinite(out).all()
