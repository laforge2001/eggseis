"""Tests for the `eggseis plugins` CLI subcommand."""

from __future__ import annotations

import textwrap

import pytest
from typer.testing import CliRunner

from eggseis import plugin_loader
from eggseis.cli import app
from eggseis.plugin import clear_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_plugins_lists_builtins(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "empty")
    monkeypatch.delenv(plugin_loader.PLUGIN_PATH_ENV, raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0
    assert "Envelope" in result.stdout
    assert "Ormsby Bandpass" in result.stdout


def test_plugins_lists_user_plugin_from_env_path(tmp_path, monkeypatch):
    pdir = tmp_path / "extra"
    pdir.mkdir()
    (pdir / "demo.py").write_text(textwrap.dedent("""
        from eggseis.plugin import Param, trace_attribute
        @trace_attribute(name="DemoCli")
        def demo(trace, k: float = Param(1.0)):
            return trace
    """))
    monkeypatch.setenv(plugin_loader.PLUGIN_PATH_ENV, str(pdir))
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "empty")
    runner = CliRunner()
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0
    assert "DemoCli" in result.stdout


def test_plugins_reports_failed_loads(tmp_path, monkeypatch):
    pdir = tmp_path / "p"
    pdir.mkdir()
    (pdir / "broken.py").write_text("def : invalid\n")
    monkeypatch.setenv(plugin_loader.PLUGIN_PATH_ENV, str(pdir))
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "empty")
    runner = CliRunner()

    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0
    assert "failed to load" in result.stdout
    assert "--show-errors" in result.stdout

    detailed = runner.invoke(app, ["plugins", "--show-errors"])
    assert detailed.exit_code == 0
    assert "broken.py" in detailed.stdout


def test_plugins_params_flag_shows_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "empty")
    monkeypatch.delenv(plugin_loader.PLUGIN_PATH_ENV, raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["plugins", "--params"])
    assert result.exit_code == 0
    assert "f_low_pass" in result.stdout  # Ormsby param
    assert "default=10.0" in result.stdout
