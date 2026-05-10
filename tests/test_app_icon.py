"""App icon resource bundled and loaded."""

from __future__ import annotations

import importlib.resources

import pytest

pytest.importorskip("PySide6")


def test_eggseis_svg_resource_present():
    p = importlib.resources.files("eggseis.resources") / "eggseis.svg"
    assert p.is_file()
    assert p.read_text(encoding="utf-8").lstrip().startswith("<")


def test_main_window_sets_window_icon(qtbot):
    from eggseis.app import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    icon = win.windowIcon()
    assert not icon.isNull(), "MainWindow.windowIcon() should be set from eggseis.svg"
