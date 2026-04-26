"""Discover plugins from built-ins, user directories, and entry points."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from importlib.metadata import entry_points
from pathlib import Path

from eggseis.plugin import PluginSpec, registered

USER_PLUGIN_DIR = Path.home() / ".eggseis" / "plugins"
PLUGIN_PATH_ENV = "EGGSEIS_PLUGIN_PATH"


def _env_path_dirs() -> list[Path]:
    """Parse `$EGGSEIS_PLUGIN_PATH` (os.pathsep-separated) into resolved Paths."""
    raw = os.environ.get(PLUGIN_PATH_ENV, "")
    dirs: list[Path] = []
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if entry:
            dirs.append(Path(entry).expanduser())
    return dirs


def resolved_user_dirs() -> list[Path]:
    """Ordered list of dirs to scan: $EGGSEIS_PLUGIN_PATH entries, then USER_PLUGIN_DIR.

    Duplicates (by `resolve()`) are removed; first occurrence wins.
    """
    seen: set[Path] = set()
    out: list[Path] = []
    for d in (*_env_path_dirs(), USER_PLUGIN_DIR):
        try:
            key = d.resolve()
        except OSError:
            key = d
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def load_builtins() -> None:
    """Import the built-ins package so all decorators fire.

    Reloads submodules if they are already imported, so the registry
    stays consistent with `eggseis.plugin._REGISTRY` (which can be
    cleared in tests).
    """
    pkg = importlib.import_module("eggseis.builtins")
    pkg_name = pkg.__name__
    for mod_name in list(sys.modules):
        if mod_name.startswith(pkg_name + "."):
            importlib.reload(sys.modules[mod_name])


def load_user_plugins(directory: Path | None = None) -> list[Path]:
    """Import every *.py file in `directory`. Errors are logged, not raised."""
    target = directory if directory is not None else USER_PLUGIN_DIR
    if not target.is_dir():
        return []
    loaded: list[Path] = []
    for path in sorted(target.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"eggseis_user_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            print(f"eggseis: failed to load plugin {path}: {exc}", file=sys.stderr)
            sys.modules.pop(mod_name, None)
            continue
        loaded.append(path)
    return loaded


def load_entry_points() -> None:
    for ep in entry_points(group="eggseis.plugins"):
        try:
            ep.load()
        except Exception as exc:
            print(f"eggseis: failed to load entry point {ep.name}: {exc}", file=sys.stderr)


def discover_all(user_dir: Path | None = None) -> tuple[PluginSpec, ...]:
    """Discover plugins from built-ins, user dirs, and entry points.

    If `user_dir` is given, only that directory is scanned (test-friendly).
    Otherwise the resolved list (`$EGGSEIS_PLUGIN_PATH` + `USER_PLUGIN_DIR`)
    is used.
    """
    load_builtins()
    if user_dir is not None:
        load_user_plugins(user_dir)
    else:
        for d in resolved_user_dirs():
            load_user_plugins(d)
    load_entry_points()
    return registered()
