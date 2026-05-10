"""Viewer theme — follow system dark/light mode for pyqtgraph plots.

The theme is read from ``QGuiApplication.palette()`` and applied at viewer
construction time. Switching the system theme while the app is running has
no effect until restart; live re-theming via ``paletteChanged`` is out of
scope for v1.0.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QPalette

# Light + dark color tokens. Tweak with PaleoScan-aesthetic feedback in mind:
# muted backgrounds, high-contrast accents, no pure black/white extremes.
_LIGHT = {
    "background": "#ffffff",
    "foreground": "#202020",
    "grid": "#cccccc",
    "axis": "#404040",
    "warning": "#aa6600",
    "slice_indicator": "#ff3333",
    "well_marker": "#2566c8",
    "accent": "#2566c8",
    "accent_muted": "#7aa9e4",
    "surface": "#fafafa",
    "surface_alt": "#f0f0f0",
    "border": "#d0d0d0",
    "text_muted": "#707070",
}

_DARK = {
    "background": "#1e1e1e",
    "foreground": "#e0e0e0",
    "grid": "#3a3a3a",
    "axis": "#a0a0a0",
    "warning": "#f4a700",
    "slice_indicator": "#ff5555",
    "well_marker": "#5c9eff",
    "accent": "#5c9eff",
    "accent_muted": "#3a6ba8",
    "surface": "#252525",
    "surface_alt": "#2a2a2a",
    "border": "#3a3a3a",
    "text_muted": "#a0a0a0",
}


def is_dark_mode() -> bool:
    """True when the system palette indicates a dark theme."""
    palette = QGuiApplication.palette()
    bg = palette.color(QPalette.ColorRole.Window)
    return bg.lightness() < 128


def colors() -> dict[str, str]:
    return _DARK if is_dark_mode() else _LIGHT


def apply_to_plot_widget(plot_widget) -> None:
    """Apply theme colors to a pyqtgraph PlotWidget — bg + axis pens + grid."""
    import pyqtgraph as pg

    c = colors()
    plot_widget.setBackground(c["background"])
    pen = pg.mkPen(c["axis"], width=1)
    text_pen = pg.mkPen(c["foreground"])
    for axis_name in ("left", "bottom", "right", "top"):
        axis = plot_widget.getPlotItem().getAxis(axis_name)
        if axis is None:
            continue
        axis.setPen(pen)
        axis.setTextPen(text_pen)
