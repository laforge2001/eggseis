"""Recent-projects ledger persisted to ~/.eggseis/recent.json.

A list of {"path": str, "timestamp": float}, newest first, capped at
RECENT_MAX. Used by the WelcomeWidget and refreshed on every successful
open_project.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)

RECENT_MAX = 5


def _ledger_path() -> Path:
    return Path.home() / ".eggseis" / "recent.json"


def load_recent() -> list[dict]:
    p = _ledger_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _log.warning("recent.json malformed; treating as empty: %s", exc)
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict) and "path" in r]


def add_recent(path: str) -> None:
    items = [r for r in load_recent() if r["path"] != path]
    items.insert(0, {"path": path, "timestamp": time.time()})
    items = items[:RECENT_MAX]
    _write(items)


def remove_recent(path: str) -> None:
    items = [r for r in load_recent() if r["path"] != path]
    _write(items)


def _write(items: list[dict]) -> None:
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")
