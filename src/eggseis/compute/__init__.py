"""eggseis compute engine — async, cancellable, cache-backed plugin execution."""

from eggseis.compute.cache import CacheKey, SectionLRU, make_cache_key, params_hash
from eggseis.compute.job import CancellationToken, Job
from eggseis.compute.orchestrator import JobOrchestrator
from eggseis.compute.tile import Tile, split_section
from eggseis.compute.worker import TileRunnable, TileSignals

__all__ = [
    "CacheKey",
    "CancellationToken",
    "Job",
    "JobOrchestrator",
    "SectionLRU",
    "Tile",
    "TileRunnable",
    "TileSignals",
    "make_cache_key",
    "params_hash",
    "split_section",
]
