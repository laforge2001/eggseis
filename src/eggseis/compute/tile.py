"""Tile slicing primitives for section-level compute jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    """A contiguous range of trace indices within a section, plus its priority key."""

    start: int          # inclusive
    stop: int           # exclusive
    priority: int       # smaller = run first

    @property
    def size(self) -> int:
        return self.stop - self.start


def split_section(n_traces: int, tile_size: int = 64) -> list[Tile]:
    """Split [0, n_traces) into tiles ordered by distance from the section midpoint."""
    if n_traces <= 0:
        return []
    mid = n_traces // 2
    tiles: list[Tile] = []
    for start in range(0, n_traces, tile_size):
        stop = min(start + tile_size, n_traces)
        center = (start + stop) // 2
        tiles.append(Tile(start=start, stop=stop, priority=abs(center - mid)))
    tiles.sort(key=lambda t: t.priority)
    return tiles
