"""Segmented status bar."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def bar(qtbot):
    from eggseis.widgets.status_bar import SegmentedStatusBar

    w = SegmentedStatusBar()
    qtbot.addWidget(w)
    return w


def test_set_project_name_updates_segment(bar):
    bar.set_project_name("dutch-f3")
    assert "dutch-f3" in bar._project_label.text()
    bar.set_project_name(None)
    assert bar._project_label.text() == "—"


def test_set_cursor_updates_segment(bar):
    bar.set_cursor(405, 750, 1200.0)
    assert "405" in bar._cursor_label.text()
    assert "750" in bar._cursor_label.text()
    bar.set_cursor(None, None, None)
    assert bar._cursor_label.text() == "—"


def test_set_cache_rate_formats_percent(bar):
    bar.set_cache_rate(0.873)
    assert "87" in bar._cache_label.text()
    assert "%" in bar._cache_label.text()


def test_version_segment_set_at_construction(bar):
    assert bar._version_label.text().startswith("v")
