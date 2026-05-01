"""project.yaml schema migrations.

Each migrator takes a `dict` parsed from `project.yaml` and returns the
upgraded version. Registered upgraders run in order to bring older
manifests to `KNOWN_SCHEMA_VERSION`. Empty for now — first real migration
lands when v1 is followed by v2.
"""

from __future__ import annotations

from collections.abc import Callable

# Maps from-version -> migrator that bumps it to from-version + 1.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def migrate(data: dict, target_version: int) -> dict:
    """Apply registered migrators until `data` reaches `target_version`."""
    current = int(data.get("schema_version", 0))
    while current < target_version:
        migrator = MIGRATIONS.get(current)
        if migrator is None:
            break  # No migrator from this version; loader handles the gap.
        data = migrator(data)
        current = int(data.get("schema_version", current + 1))
    return data
