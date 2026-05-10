"""apply_theme + theme_signals integration tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qdarktheme")


@pytest.fixture
def qapp(qtbot):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    assert app is not None
    return app


@pytest.fixture(autouse=True)
def _reset_style_module():
    """Reset module-global state so tests are order-independent.

    `eggseis.style` keeps `_current_mode` at module scope
    (intentionally — apply_theme is process-singleton). Without this
    reset, prior tests would leak state into the idempotency test.
    Also disconnects any signal handlers attached in prior tests.
    """
    try:
        from eggseis import style as _style
        from eggseis.viewers import theme as _theme
    except ImportError:
        yield
        return

    import warnings

    _style._current_mode = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            _style.theme_signals.themeChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
    _theme.set_active_mode(None)
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            _style.theme_signals.themeChanged.disconnect()
        except (RuntimeError, TypeError):
            pass


def test_theme_enum_values():
    from eggseis.style import Theme
    assert Theme.DARK.value == "dark"
    assert Theme.LIGHT.value == "light"


def test_apply_theme_updates_current_mode(qapp):
    from eggseis.style import Theme, apply_theme, current_mode
    apply_theme(Theme.DARK)
    assert current_mode() is Theme.DARK
    apply_theme(Theme.LIGHT)
    assert current_mode() is Theme.LIGHT


def test_apply_theme_sets_application_stylesheet(qapp):
    from eggseis.style import Theme, apply_theme
    apply_theme(Theme.DARK)
    sheet = qapp.styleSheet()
    assert sheet  # non-empty


def test_theme_changed_signal_fires_once(qapp, qtbot):
    from eggseis.style import Theme, apply_theme, theme_signals
    received = []
    theme_signals.themeChanged.connect(lambda mode: received.append(mode))
    apply_theme(Theme.LIGHT)
    apply_theme(Theme.DARK)
    assert received == [Theme.LIGHT, Theme.DARK]


def test_apply_theme_idempotent(qapp):
    from eggseis.style import Theme, apply_theme, theme_signals
    received = []
    theme_signals.themeChanged.connect(lambda mode: received.append(mode))
    apply_theme(Theme.DARK)
    apply_theme(Theme.DARK)  # second call is no-op
    assert received.count(Theme.DARK) == 1


def test_apply_theme_bad_mode_falls_back(qapp, caplog):
    from eggseis.style import Theme, apply_theme, current_mode
    apply_theme(Theme.DARK)
    # Pass a value that bypasses the enum to simulate corrupt persisted state.
    apply_theme("invalid")  # type: ignore[arg-type]
    # Falls back to current mode; no crash.
    assert current_mode() is Theme.DARK
