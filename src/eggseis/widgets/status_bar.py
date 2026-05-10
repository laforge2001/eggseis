"""Segmented status bar — project, cursor coords, cache rate, version."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from PySide6.QtWidgets import QLabel, QStatusBar


class SegmentedStatusBar(QStatusBar):
    """Status bar with permanent segments separated by spacers."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizeGripEnabled(False)

        self._project_label = QLabel("—")
        self._cursor_label = QLabel("—")
        self._cache_label = QLabel("cache —")
        try:
            v = f"v{_pkg_version('eggseis')}"
        except Exception:
            v = "v0.0.0"
        self._version_label = QLabel(v)

        for label in (self._project_label, self._cursor_label, self._cache_label):
            self.addPermanentWidget(_separator())
            self.addPermanentWidget(label)
        self.addPermanentWidget(_separator())
        self.addPermanentWidget(self._version_label)

    def set_project_name(self, name: str | None) -> None:
        self._project_label.setText(name if name else "—")

    def set_cursor(self, inline: int | None, xline: int | None, t_ms: float | None) -> None:
        if inline is None or xline is None or t_ms is None:
            self._cursor_label.setText("—")
            return
        self._cursor_label.setText(f"il {inline} · xl {xline} · t {t_ms / 1000:.2f}s")

    def set_cache_rate(self, fraction: float) -> None:
        pct = max(0.0, min(1.0, fraction)) * 100
        self._cache_label.setText(f"cache {pct:.0f}%")


def _separator() -> QLabel:
    sep = QLabel("·")
    sep.setStyleSheet("color: palette(mid);")
    return sep
