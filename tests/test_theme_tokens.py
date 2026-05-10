"""New theme tokens added during UX polish — accent palette + chrome."""

from __future__ import annotations

from eggseis.viewers.theme import _DARK, _LIGHT, colors


def test_dark_palette_has_new_chrome_tokens():
    for token in ("accent", "accent_muted", "surface", "surface_alt", "border", "text_muted"):
        assert token in _DARK, f"missing {token!r} in dark palette"


def test_light_palette_has_new_chrome_tokens():
    for token in ("accent", "accent_muted", "surface", "surface_alt", "border", "text_muted"):
        assert token in _LIGHT, f"missing {token!r} in light palette"


def test_dark_accent_distinct_from_light_accent():
    assert _DARK["accent"] != _LIGHT["accent"]


def test_colors_returns_active_palette():
    c = colors()
    assert "accent" in c
    assert "well_marker" in c  # existing token still present
