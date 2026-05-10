"""Recent-projects ledger persisted to ~/.eggseis/recent.json."""

from __future__ import annotations

from eggseis.recent import (
    RECENT_MAX,
    add_recent,
    load_recent,
    remove_recent,
)


def test_load_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_recent() == []


def test_add_dedupes_and_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for i in range(RECENT_MAX + 3):
        add_recent(f"/p{i}")
    assert len(load_recent()) == RECENT_MAX
    add_recent("/p0")
    paths = [r["path"] for r in load_recent()]
    assert paths[0] == "/p0"
    assert paths.count("/p0") == 1


def test_load_recovers_from_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".eggseis").mkdir()
    (tmp_path / ".eggseis" / "recent.json").write_text("not json {")
    assert load_recent() == []


def test_remove_drops_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    add_recent("/p1")
    add_recent("/p2")
    remove_recent("/p1")
    assert [r["path"] for r in load_recent()] == ["/p2"]
