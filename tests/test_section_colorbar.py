"""SectionViewer cmap selection + colorbar."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_set_colormap_changes_active_lut(qtbot):
    from eggseis.viewers.section import SectionViewer
    sv = SectionViewer()
    qtbot.addWidget(sv)
    sv.set_colormap("vik")
    assert sv.current_cmap == "vik"


def test_unknown_cmap_falls_back_to_default(qtbot):
    from eggseis.viewers.section import SectionViewer
    sv = SectionViewer()
    qtbot.addWidget(sv)
    sv.set_colormap("nonexistent")
    from eggseis.colormaps import DEFAULT_AMPLITUDE
    assert sv.current_cmap == DEFAULT_AMPLITUDE


def test_default_amplitude_for_raw_source(qtbot):
    """Raw Source path uses DEFAULT_AMPLITUDE."""
    from eggseis.colormaps import DEFAULT_AMPLITUDE
    from eggseis.viewers.section import SectionViewer
    sv = SectionViewer()
    qtbot.addWidget(sv)
    assert sv.current_cmap == DEFAULT_AMPLITUDE


def test_theme_changed_signal_refreshes_colorbar(qtbot):
    from eggseis.style import Theme, apply_theme
    from eggseis.viewers.section import SectionViewer
    sv = SectionViewer()
    qtbot.addWidget(sv)
    apply_theme(Theme.LIGHT)
    apply_theme(Theme.DARK)
