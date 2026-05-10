"""Theme application and runtime token signal.

Combines pyqtdarktheme's base Qt stylesheet with our own override QSS
that injects the eggseis accent palette and chrome tweaks. Exposes a
single QObject (`theme_signals`) carrying `themeChanged(Theme)` so
viewers can re-apply pen/brush colors on toggle.
"""

from __future__ import annotations

import importlib.resources
import logging
from enum import StrEnum

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from eggseis.viewers import theme as _theme

_log = logging.getLogger(__name__)


class Theme(StrEnum):
    DARK = "dark"
    LIGHT = "light"


class _ThemeSignals(QObject):
    themeChanged = Signal(Theme)


theme_signals = _ThemeSignals()
_current_mode: Theme | None = None


def current_mode() -> Theme:
    """Return the active theme, defaulting to DARK before first apply."""
    return _current_mode if _current_mode is not None else Theme.DARK


def apply_theme(mode: Theme) -> None:
    """Install pyqtdarktheme + override QSS for `mode`. Idempotent."""
    global _current_mode

    if not isinstance(mode, Theme):
        try:
            mode = Theme(mode)
        except ValueError:
            _log.warning("apply_theme: invalid mode %r; keeping %s", mode, _current_mode)
            return

    app = QApplication.instance()
    if mode is _current_mode and app is not None and app.styleSheet():
        return  # already applied; skip duplicate signal

    if app is None:
        _current_mode = mode
        return

    base_sheet = ""
    try:
        import qdarktheme

        qdarktheme.setup_theme(mode.value)
        base_sheet = app.styleSheet()
    except Exception as exc:  # pragma: no cover — defensive
        _log.warning("qdarktheme setup failed: %s", exc)

    _theme.set_active_mode(mode.value)
    overrides = _load_overrides()
    app.setStyleSheet(base_sheet + "\n" + overrides)

    _current_mode = mode
    theme_signals.themeChanged.emit(mode)


def _load_overrides() -> str:
    """Read the shared override QSS and substitute active-mode palette tokens."""
    qss_name = "overrides.qss"
    try:
        resource = importlib.resources.files("eggseis.style.qss") / qss_name
        raw = resource.read_text(encoding="utf-8")
    except FileNotFoundError:
        _log.warning("override QSS %s missing; skipping override layer", qss_name)
        return ""

    tokens = _theme.colors()
    try:
        return raw.format(**tokens)
    except KeyError as exc:
        _log.warning("override QSS %s references unknown token %s; skipping", qss_name, exc)
        return ""
