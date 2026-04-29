"""Tests for the compute cache primitives."""

from __future__ import annotations

import numpy as np

from eggseis.compute.cache import CacheKey, SectionLRU, params_hash


def test_params_hash_stable_across_key_order():
    assert params_hash({"a": 1, "b": 2.0}) == params_hash({"b": 2.0, "a": 1})


def test_params_hash_changes_on_value_change():
    assert params_hash({"k": 1.0}) != params_hash({"k": 1.0001})


def test_params_hash_handles_nested_lists():
    assert params_hash({"taps": [1, 2, 3]}) == params_hash({"taps": [1, 2, 3]})
    assert params_hash({"taps": [1, 2, 3]}) != params_hash({"taps": [3, 2, 1]})


def _key(i: int) -> CacheKey:
    return CacheKey(
        plugin_id="p",
        plugin_version="0.1.0",
        chain_hash="h",
        axis="inline",
        index=i,
        volume_version=("mdio", "/x", 1, 1),
    )


def test_lru_get_returns_none_when_missing():
    cache = SectionLRU()
    assert cache.get(_key(0)) is None


def test_lru_put_then_get_returns_array():
    cache = SectionLRU()
    arr = np.zeros((4,), dtype=np.float32)
    cache.put(_key(0), arr)
    assert cache.get(_key(0)) is arr


def test_lru_evicts_oldest_when_over_budget():
    cache = SectionLRU(byte_budget=8 * 1024)
    a = np.zeros((1024,), dtype=np.float32)  # 4 KB
    b = np.zeros((1024,), dtype=np.float32)
    c = np.zeros((1024,), dtype=np.float32)
    cache.put(_key(0), a)
    cache.put(_key(1), b)
    cache.put(_key(2), c)
    assert cache.get(_key(0)) is None
    assert cache.get(_key(1)) is not None
    assert cache.get(_key(2)) is not None
    assert cache.nbytes <= 8 * 1024


def test_lru_get_marks_entry_as_recently_used():
    cache = SectionLRU(byte_budget=8 * 1024)
    a = np.zeros((1024,), dtype=np.float32)
    b = np.zeros((1024,), dtype=np.float32)
    c = np.zeros((1024,), dtype=np.float32)
    cache.put(_key(0), a)
    cache.put(_key(1), b)
    cache.get(_key(0))
    cache.put(_key(2), c)
    assert cache.get(_key(0)) is not None
    assert cache.get(_key(1)) is None


def test_lru_drops_silently_when_value_exceeds_budget():
    cache = SectionLRU(byte_budget=64)
    big = np.zeros((100,), dtype=np.float32)  # 400 bytes
    cache.put(_key(0), big)
    assert len(cache) == 0
    assert cache.nbytes == 0


def test_make_cache_key_uses_chain_hash_override_when_provided(fake_backend):
    from eggseis.compute.cache import make_cache_key, params_hash
    from eggseis.data import SeismicVolume

    class _StubSpec:
        id = "p"
        version = "0.1.0"

    class _StubParams:
        def model_dump(self):
            return {"a": 1}

    volume = SeismicVolume(fake_backend, name="v")
    key = make_cache_key(
        _StubSpec(), _StubParams(), volume, "inline", 0, chain_hash="deadbeef"
    )
    assert key.chain_hash == "deadbeef"

    # Default path: no chain_hash kwarg → uses params_hash(model_dump()).
    key_default = make_cache_key(_StubSpec(), _StubParams(), volume, "inline", 0)
    expected = params_hash({"a": 1})
    assert key_default.chain_hash == expected
