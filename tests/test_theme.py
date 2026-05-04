"""Viewer theme — light/dark detection + plot widget application."""

from __future__ import annotations


def test_is_dark_mode_returns_bool(qtbot):
    from eggseis.viewers.theme import is_dark_mode

    assert isinstance(is_dark_mode(), bool)


def test_colors_returns_required_keys(qtbot):
    from eggseis.viewers.theme import colors

    c = colors()
    for key in ("background", "foreground", "grid", "axis", "warning"):
        assert key in c, f"theme missing {key}"


def test_apply_to_plot_widget_sets_background(qtbot):
    import pyqtgraph as pg

    from eggseis.viewers.theme import apply_to_plot_widget, colors

    pw = pg.PlotWidget()
    qtbot.addWidget(pw)
    apply_to_plot_widget(pw)
    # Background brush should match the theme's background color.
    bg = pw.backgroundBrush().color().name()
    assert bg == colors()["background"]
