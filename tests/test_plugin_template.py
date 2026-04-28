"""Tests for the plugin template generator."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from eggseis.plugin import clear_registry, registered
from eggseis.plugin_template import _slugify, create_template


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_slugify_handles_punctuation_and_spaces():
    assert _slugify("My Filter") == "my_filter"
    assert _slugify("AGC (per-trace)") == "agc_per_trace"
    assert _slugify("1st version") == "_1st_version"


def test_slugify_rejects_empty():
    with pytest.raises(ValueError):
        _slugify("???")


def test_create_template_writes_file(tmp_path):
    path = create_template("My Demo", target_dir=tmp_path)
    assert path == tmp_path / "my_demo.py"
    assert path.is_file()
    content = path.read_text()
    assert '@trace_attribute(name="My Demo"' in content
    assert "def my_demo(" in content


def test_create_template_existing_file_raises(tmp_path):
    create_template("X", target_dir=tmp_path)
    with pytest.raises(FileExistsError):
        create_template("X", target_dir=tmp_path)


def test_template_does_not_embed_target_path(tmp_path):
    """Regression: paths with backslashes (Windows) used to break docstrings."""
    path = create_template("Round Trip", target_dir=tmp_path)
    content = path.read_text()
    assert str(tmp_path) not in content
    # `\U`, `\N`, `\x` etc. are unicode-escape sequences; the docstring
    # must not contain a path that introduces them.
    assert "\\U" not in content
    assert "\\N" not in content


def test_template_imports_and_registers(tmp_path):
    """The generated file must be valid Python and register a plugin."""
    path = create_template("Round Trip", target_dir=tmp_path)
    spec = importlib.util.spec_from_file_location("eggseis_user_round_trip", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        names = [s.name for s in registered()]
        assert "Round Trip" in names
    finally:
        sys.modules.pop(spec.name, None)
