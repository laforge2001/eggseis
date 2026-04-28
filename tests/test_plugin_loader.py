"""Tests for plugin discovery: built-ins, user dir, entry points."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from eggseis import plugin_loader
from eggseis.plugin import clear_registry, registered
from eggseis.plugin_loader import (
    PLUGIN_PATH_ENV,
    clear_load_errors,
    discover_all,
    load_builtins,
    load_errors,
    load_user_plugins,
    resolved_user_dirs,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_load_builtins_registers_five():
    load_builtins()
    names = {s.name for s in registered()}
    assert {
        "Envelope",
        "Instantaneous Phase",
        "Instantaneous Frequency",
        "RMS Amplitude",
        "Ormsby Bandpass",
    } <= names


def test_load_user_plugins_from_directory(tmp_path):
    plugin_file = tmp_path / "myplug.py"
    plugin_file.write_text(textwrap.dedent("""
        import numpy as np
        from eggseis.plugin import Param, trace_attribute

        @trace_attribute(name="MyPlug")
        def myplug(trace, k: float = Param(1.5)):
            return trace * k
    """))
    loaded = load_user_plugins(tmp_path)
    assert plugin_file in loaded
    names = {s.name for s in registered()}
    assert "MyPlug" in names


def test_load_user_plugins_skips_underscore_prefixed(tmp_path):
    (tmp_path / "_helper.py").write_text("x = 1\n")
    (tmp_path / "real.py").write_text(textwrap.dedent("""
        from eggseis.plugin import Param, trace_attribute
        @trace_attribute(name="Real")
        def real(trace, k: float = Param(1.0)):
            return trace
    """))
    loaded = load_user_plugins(tmp_path)
    assert all(p.name != "_helper.py" for p in loaded)
    assert {s.name for s in registered()} == {"Real"}


def test_load_user_plugins_swallows_errors(tmp_path, capsys):
    (tmp_path / "broken.py").write_text("this is not valid python !!!\n")
    (tmp_path / "ok.py").write_text(textwrap.dedent("""
        from eggseis.plugin import Param, trace_attribute
        @trace_attribute(name="OK")
        def ok(trace, k: float = Param(1.0)):
            return trace
    """))
    loaded = load_user_plugins(tmp_path)
    # broken.py was attempted but not in loaded list
    assert (tmp_path / "broken.py") not in loaded
    assert (tmp_path / "ok.py") in loaded
    err = capsys.readouterr().err
    assert "failed to load plugin" in err
    assert "broken.py" in err


def test_load_user_plugins_missing_dir_returns_empty(tmp_path):
    assert load_user_plugins(tmp_path / "does-not-exist") == []


def test_discover_all_combines_sources(tmp_path):
    plugin_file = tmp_path / "extra.py"
    plugin_file.write_text(textwrap.dedent("""
        from eggseis.plugin import Param, trace_attribute
        @trace_attribute(name="Extra")
        def extra(trace, k: float = Param(1.0)):
            return trace
    """))
    specs = discover_all(user_dir=tmp_path)
    names = {s.name for s in specs}
    assert "Envelope" in names  # built-in
    assert "Extra" in names      # user


def _write_plugin(dir: Path, filename: str, name: str) -> Path:
    f = dir / filename
    f.write_text(textwrap.dedent(f"""
        from eggseis.plugin import Param, trace_attribute
        @trace_attribute(name="{name}")
        def fn(trace, k: float = Param(1.0)):
            return trace
    """))
    return f


def test_env_path_loads_multiple_dirs(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write_plugin(a, "alpha.py", "FromA")
    _write_plugin(b, "beta.py", "FromB")

    monkeypatch.setenv(PLUGIN_PATH_ENV, f"{a}{os.pathsep}{b}")
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "no-default")

    specs = discover_all()
    names = {s.name for s in specs}
    assert {"FromA", "FromB"} <= names


def test_env_path_combined_with_default_user_dir(tmp_path, monkeypatch):
    env_dir = tmp_path / "env"
    user_dir = tmp_path / "user"
    env_dir.mkdir()
    user_dir.mkdir()
    _write_plugin(env_dir, "env_plug.py", "EnvPlug")
    _write_plugin(user_dir, "user_plug.py", "UserPlug")

    monkeypatch.setenv(PLUGIN_PATH_ENV, str(env_dir))
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", user_dir)

    specs = discover_all()
    names = {s.name for s in specs}
    assert "EnvPlug" in names
    assert "UserPlug" in names


def test_resolved_dirs_dedups(tmp_path, monkeypatch):
    d = tmp_path / "shared"
    d.mkdir()
    monkeypatch.setenv(PLUGIN_PATH_ENV, f"{d}{os.pathsep}{d}")
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", d)
    dirs = resolved_user_dirs()
    assert len(dirs) == 1


def test_load_errors_captures_broken_file(tmp_path, monkeypatch):
    (tmp_path / "broken.py").write_text("nope nope this is not python\n")
    monkeypatch.setenv(PLUGIN_PATH_ENV, "")
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "ignored")
    clear_load_errors()
    load_user_plugins(tmp_path)
    errs = load_errors()
    assert len(errs) == 1
    assert errs[0].source.endswith("broken.py")
    assert errs[0].message  # non-empty


def test_discover_all_clears_prior_errors(tmp_path, monkeypatch):
    bad = tmp_path / "broken.py"
    bad.write_text("syntaxerror !!\n")
    monkeypatch.setenv(PLUGIN_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "missing")

    discover_all()
    assert len(load_errors()) == 1

    # Fix the file; next discover should succeed and clear the error list.
    bad.write_text(
        "from eggseis.plugin import Param, trace_attribute\n"
        "@trace_attribute(name='Fixed')\n"
        "def f(trace, k: float = Param(1.0)):\n"
        "    return trace\n"
    )
    discover_all()
    assert load_errors() == ()


def test_explicit_user_dir_overrides_env(tmp_path, monkeypatch):
    """When `discover_all(user_dir=...)` is given, env path is ignored."""
    explicit = tmp_path / "explicit"
    env_dir = tmp_path / "env"
    explicit.mkdir()
    env_dir.mkdir()
    _write_plugin(explicit, "x.py", "Explicit")
    _write_plugin(env_dir, "e.py", "FromEnv")

    monkeypatch.setenv(PLUGIN_PATH_ENV, str(env_dir))
    monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path / "ignored")

    specs = discover_all(user_dir=explicit)
    names = {s.name for s in specs}
    assert "Explicit" in names
    assert "FromEnv" not in names
