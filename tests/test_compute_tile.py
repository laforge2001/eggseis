"""Tests for tile slicing and ordering."""

from __future__ import annotations

from eggseis.compute.tile import Tile, split_section


def test_split_section_covers_full_range():
    tiles = split_section(200, tile_size=64)
    spans = sorted((t.start, t.stop) for t in tiles)
    assert spans[0][0] == 0
    assert spans[-1][1] == 200
    for (a_start, a_stop), (b_start, b_stop) in zip(spans, spans[1:]):
        assert a_stop == b_start


def test_split_section_orders_center_first():
    tiles = split_section(200, tile_size=64)
    midpoint = 100
    first = tiles[0]
    last = tiles[-1]
    first_dist = abs(((first.start + first.stop) // 2) - midpoint)
    last_dist = abs(((last.start + last.stop) // 2) - midpoint)
    assert first_dist < last_dist


def test_split_section_handles_partial_final_tile():
    tiles = split_section(100, tile_size=64)
    sizes = sorted(t.size for t in tiles)
    assert sizes == [36, 64]


def test_split_section_single_tile_when_smaller_than_tile_size():
    tiles = split_section(40, tile_size=64)
    assert len(tiles) == 1
    assert tiles[0] == Tile(start=0, stop=40, priority=0) or tiles[0].size == 40
