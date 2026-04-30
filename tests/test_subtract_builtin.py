"""Test the M6 multi-input `subtract` builtin plugin."""

from __future__ import annotations

import numpy as np


def test_subtract_module_imports_and_registers():
    from eggseis.builtins.subtract import subtract
    spec = subtract._eggseis_spec
    assert spec.inputs == ("a", "b")
    assert spec.output == "out"
    assert spec.deterministic is True


def test_subtract_returns_a_minus_b():
    from eggseis.builtins.subtract import subtract
    a = np.array([10.0, 20.0, 30.0])
    b = np.array([1.0, 4.0, 9.0])
    np.testing.assert_array_equal(
        subtract._eggseis_spec.func(a, b),
        np.array([9.0, 16.0, 21.0]),
    )


def test_subtract_2d_section_shapes():
    from eggseis.builtins.subtract import subtract
    a = np.ones((100, 50), dtype=np.float32) * 5.0
    b = np.ones((100, 50), dtype=np.float32) * 2.0
    out = subtract._eggseis_spec.func(a, b)
    assert out.shape == (100, 50)
    np.testing.assert_allclose(out, np.full_like(out, 3.0))
