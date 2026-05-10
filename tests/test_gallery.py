"""eggseis.gallery renders themed widgets to PNG for visual regression."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_gallery_main_renders_pngs(qtbot, tmp_path):
    from eggseis.gallery import render_all

    out = tmp_path / "gallery"
    written = render_all(out)
    expected = {
        "welcome.png",
        "section_vik.png",
        "section_batlow.png",
        "section_gray.png",
        "map_view.png",
        "log_panel.png",
    }
    names = {p.name for p in written}
    assert expected.issubset(names)
    for path in written:
        assert path.stat().st_size > 0
