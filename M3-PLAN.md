# M3 — "The plugin runs"

**Milestone 3 of the eggseis development roadmap. See `ROADMAP.md` for the full plan and `M2-PLAN.md` for the milestone that precedes this one.**

---

## Goal

Make `eggseis` extensible. Drop a `my_attribute.py` file in a plugin folder; the function appears in an Attribute menu; selecting it applies the function to the visible section and paints the result back. Parameters declared on the function auto-generate a Qt dialog.

The point of M3 is to **prove the plugin API is real and ergonomic.** Not to ship a polished marketplace. Not to thread the compute. Not to handle windows or volumes. Just trace-local attributes, run synchronously on the visible slice, with a parameter dialog that came for free from the decoration.

If a second person can write a working plugin in 30 minutes given only the docs, M3 is done. If they can't, the API isn't right yet — fix it before moving on.

## Exit criteria

You're done with M3 when this is true:

- A function decorated with `@trace_attribute` in a file under `~/.eggseis/plugins/` (or an installed entry point) appears in the GUI's `Attribute` menu after restart.
- Selecting the plugin applies it to the currently displayed section and paints the result.
- Changing parameters in the auto-generated dialog re-runs the plugin and updates the view.
- Five built-in plugins ship in-tree: `envelope`, `instantaneous_phase`, `instantaneous_frequency`, `rms_amplitude`, `ormsby_bandpass`.
- `File → New Plugin…` writes a working skeleton file to the user plugin directory and opens it in the system editor.
- Headless tests cover: decorator registration, parameter schema → widget generation, plugin discovery, end-to-end "select attribute → painted section" flow.
- One non-author runs through `docs/plugin-authoring.md` and writes a plugin in under 30 minutes.

---

## Locked design decisions for M3

| Area | Decision |
|---|---|
| Plugin tier | Trace-local (Tier 1) only. Function takes a single trace; framework handles fan-out. |
| Plugin data model | NumPy `np.ndarray` traces + a `context` dict (sample_rate_ms, inline, xline, etc.) |
| Vectorization | `vectorized=False` default. Opt in via `@trace_attribute(vectorized=True)` to receive a 2D batch. |
| Parameter schema | Pydantic v2 models built from `Param(...)` field declarations. |
| Parameter UI | magicgui — auto-render a Qt widget from the pydantic model. No hand-rolled dialogs in M3. |
| Discovery | Two sources: (1) `*.py` files in `~/.eggseis/plugins/`, (2) `eggseis.plugins` entry points in installed packages. |
| Execution | Synchronous on the GUI thread for M3. Threading + cache + cancellation = M4. |
| Result rendering | Replace the section image with the attribute output; original toggleable via `View → Show Source`. |
| Determinism flag | `deterministic=True` default. Lays groundwork for M4 cache; not used yet in M3. |
| Built-in plugins | Live in `src/eggseis/builtins/` and register via the same `@trace_attribute` decorator the user-facing API uses. No "internal" path. |

---

## Step 1: Add plugin dependencies

Update `pyproject.toml` `gui` extra (and add a `plugins` group if you want CLI-only plugin authoring without the full GUI — optional):

```toml
[project.optional-dependencies]
gui = [
    "pyside6>=6.6",
    "pyqtgraph>=0.13",
    "pyyaml>=6.0",
    "pydantic>=2.7",
    "magicgui>=0.9",
    "scipy>=1.13",
]
```

`scipy` lands here because every M3 built-in (envelope, instantaneous phase/frequency, Ormsby bandpass) leans on `scipy.signal` and `scipy.fft`. Keep it under `gui` for now; if a future CLI command needs to run plugins headless, promote to a `plugins` extra.

Smoke test:

```bash
pip install -e ".[dev]"
python -c "import pydantic, magicgui, scipy; print(pydantic.VERSION, magicgui.__version__, scipy.__version__)"
```

## Step 2: Plugin module — decorator + Param

```python
# src/eggseis/plugin.py
"""Plugin API: @trace_attribute decorator and Param declarations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, create_model


@dataclass(frozen=True)
class Param:
    """User-facing parameter declaration. Translated into a pydantic field."""

    default: Any
    label: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    units: str | None = None
    description: str | None = None
    choices: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class PluginSpec:
    id: str                    # "user.envelope" or "eggseis.envelope"
    name: str                  # display name
    func: Callable[..., np.ndarray]
    param_model: type[BaseModel]
    vectorized: bool
    deterministic: bool
    version: str
    source_path: str | None    # for user plugins


_REGISTRY: dict[str, PluginSpec] = {}


def trace_attribute(
    *,
    name: str | None = None,
    version: str = "0.1.0",
    vectorized: bool = False,
    deterministic: bool = True,
) -> Callable[[Callable[..., np.ndarray]], Callable[..., np.ndarray]]:
    """Decorate a function as a trace-local seismic attribute.

    The function signature determines the parameter dialog. Each non-trace
    argument with a `Param(...)` default becomes a pydantic field, then a
    magicgui widget. The `trace` argument and an optional `context` dict are
    treated specially.
    """

    def decorator(func: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
        sig = inspect.signature(func)
        fields: dict[str, tuple[type, Any]] = {}
        for pname, param in sig.parameters.items():
            if pname in ("trace", "traces", "context"):
                continue
            if not isinstance(param.default, Param):
                raise TypeError(
                    f"{func.__name__}: parameter {pname!r} must declare a "
                    f"Param(...) default"
                )
            p: Param = param.default
            ftype = param.annotation if param.annotation is not inspect.Parameter.empty else type(p.default)
            field = Field(
                default=p.default,
                title=p.label or pname,
                description=p.description,
                ge=p.min,
                le=p.max,
                json_schema_extra={
                    "step": p.step,
                    "units": p.units,
                    "choices": list(p.choices) if p.choices else None,
                },
            )
            fields[pname] = (ftype, field)

        model = create_model(
            f"{func.__name__.title()}Params",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )

        plugin_id = f"{func.__module__}.{func.__name__}"
        spec = PluginSpec(
            id=plugin_id,
            name=name or func.__name__.replace("_", " ").title(),
            func=func,
            param_model=model,
            vectorized=vectorized,
            deterministic=deterministic,
            version=version,
            source_path=getattr(inspect.getmodule(func), "__file__", None),
        )
        _REGISTRY[plugin_id] = spec
        func._eggseis_spec = spec  # type: ignore[attr-defined]
        return func

    return decorator


def registered() -> tuple[PluginSpec, ...]:
    return tuple(_REGISTRY.values())


def clear_registry() -> None:
    """Test helper. Don't call from app code."""
    _REGISTRY.clear()
```

Keep this file the **only** place plugins are defined. Built-ins, user files, third-party packages — they all decorate the same way.

## Step 3: Plugin discovery

```python
# src/eggseis/plugin_loader.py
from __future__ import annotations

import importlib
import importlib.util
import sys
from importlib.metadata import entry_points
from pathlib import Path

from eggseis.plugin import PluginSpec, registered

USER_PLUGIN_DIR = Path.home() / ".eggseis" / "plugins"


def load_builtins() -> None:
    """Import every module under eggseis.builtins so its decorators fire."""
    import eggseis.builtins  # noqa: F401  triggers package __init__


def load_user_plugins(directory: Path = USER_PLUGIN_DIR) -> list[Path]:
    """Import every *.py file in `directory`. Errors are collected, not raised."""
    if not directory.is_dir():
        return []
    loaded: list[Path] = []
    for path in sorted(directory.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"eggseis_user_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            print(f"eggseis: failed to load plugin {path}: {exc}", file=sys.stderr)
            continue
        loaded.append(path)
    return loaded


def load_entry_points() -> None:
    for ep in entry_points(group="eggseis.plugins"):
        try:
            ep.load()
        except Exception as exc:  # noqa: BLE001
            print(f"eggseis: failed to load entry point {ep.name}: {exc}", file=sys.stderr)


def discover_all() -> tuple[PluginSpec, ...]:
    load_builtins()
    load_user_plugins()
    load_entry_points()
    return registered()
```

## Step 4: Built-in plugins

```
src/eggseis/builtins/
├── __init__.py          # imports each module so decorators register
├── envelope.py
├── instantaneous_phase.py
├── instantaneous_frequency.py
├── rms_amplitude.py
└── ormsby_bandpass.py
```

```python
# src/eggseis/builtins/envelope.py
from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="Envelope", version="0.1.0")
def envelope(trace: np.ndarray) -> np.ndarray:
    return np.abs(hilbert(trace)).astype(np.float32)
```

```python
# src/eggseis/builtins/ormsby_bandpass.py
from __future__ import annotations

import numpy as np
from scipy.signal import firwin, filtfilt

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="Ormsby Bandpass", version="0.1.0")
def ormsby_bandpass(
    trace: np.ndarray,
    context: dict,
    f1: float = Param(5.0, label="Low cut", min=0.5, max=200.0, units="Hz"),
    f2: float = Param(10.0, label="Low pass", min=0.5, max=200.0, units="Hz"),
    f3: float = Param(60.0, label="High pass", min=0.5, max=200.0, units="Hz"),
    f4: float = Param(80.0, label="High cut", min=0.5, max=200.0, units="Hz"),
    n_taps: int = Param(101, label="Filter taps", min=11, max=501, step=2),
) -> np.ndarray:
    fs = 1000.0 / context["sample_rate_ms"]
    taps = firwin(n_taps, [f2, f3], pass_zero=False, fs=fs, window="hamming")
    return filtfilt(taps, 1.0, trace).astype(np.float32)
```

The other three follow the same shape. Keep each implementation **short** — these double as worked examples in the docs.

## Step 5: Plugin runner

```python
# src/eggseis/plugin_runner.py
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from eggseis.data import SeismicVolume
from eggseis.plugin import PluginSpec


def run_on_section(
    spec: PluginSpec,
    params: BaseModel,
    volume: SeismicVolume,
    axis: str,
    index: int,
) -> np.ndarray:
    """Run a trace-local plugin across every trace in the visible section."""
    if axis == "inline":
        section = volume.read_inline(index)        # (n_xlines, n_samples)
    elif axis == "xline":
        section = volume.read_xline(index)         # (n_inlines, n_samples)
    else:
        section = volume.read_timeslice(index)     # (n_inlines, n_xlines) — Tier 1 N/A

    g = volume.geometry
    context = {"sample_rate_ms": g.sample_rate_ms, "axis": axis, "index": index}
    p = params.model_dump()

    if axis == "timeslice":
        # trace-local attributes don't apply to a horizontal slice; return as-is
        return section

    if spec.vectorized:
        return spec.func(traces=section, context=context, **p).astype(np.float32)

    out = np.empty_like(section, dtype=np.float32)
    for i in range(section.shape[0]):
        sig = spec.func.__wrapped__ if hasattr(spec.func, "__wrapped__") else spec.func
        # Pass context only if the function declares it
        kwargs = dict(p)
        if "context" in sig.__code__.co_varnames:
            kwargs["context"] = context
        out[i] = spec.func(section[i], **kwargs)
    return out
```

Synchronous and trivial. M4 wraps this in a worker pool with debounce + cancel.

## Step 6: GUI integration

### 6a — Attribute menu

In `eggseis.app.MainWindow`:

```python
def _build_menus(self) -> None:
    ...
    m_attr = self.menuBar().addMenu("&Attribute")
    a_none = QAction("None (raw amplitude)", self, checkable=True, checked=True)
    a_none.triggered.connect(self._clear_attribute)
    m_attr.addAction(a_none)
    m_attr.addSeparator()

    for spec in discover_all():
        a = QAction(spec.name, self, checkable=True)
        a.triggered.connect(lambda _checked, s=spec: self._activate_attribute(s))
        m_attr.addAction(a)

    m_attr.addSeparator()
    a_new = QAction("&New Plugin…", self)
    a_new.triggered.connect(self._new_plugin_from_template)
    m_attr.addAction(a_new)
```

### 6b — Parameter dock

```python
# src/eggseis/widgets/param_dock.py
from __future__ import annotations

from magicgui import magicgui
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from eggseis.plugin import PluginSpec


class ParamDock(QWidget):
    paramsChanged = Signal(object)  # emits the validated pydantic model

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._gui = None

    def set_plugin(self, spec: PluginSpec | None) -> None:
        if self._gui is not None:
            self._layout.removeWidget(self._gui.native)
            self._gui.native.deleteLater()
            self._gui = None
        if spec is None:
            return

        defaults = spec.param_model().model_dump()

        @magicgui(auto_call=True, **{k: {"value": v} for k, v in defaults.items()})
        def panel(**kwargs):
            try:
                model = spec.param_model(**kwargs)
            except Exception:
                return
            self.paramsChanged.emit(model)

        self._gui = panel
        self._layout.addWidget(panel.native)
```

`auto_call=True` re-emits on every edit. M3 stays synchronous; M4 will debounce upstream.

### 6c — Wire it up

```python
def _activate_attribute(self, spec: PluginSpec) -> None:
    self._active_plugin = spec
    self.param_dock.set_plugin(spec)
    # initial run with defaults
    self._on_params_changed(spec.param_model())

def _on_params_changed(self, params) -> None:
    if self._active_plugin is None or self.section_viewer._volume is None:
        return
    arr = run_on_section(
        self._active_plugin,
        params,
        self.section_viewer._volume,
        self.section_viewer.current_axis,
        self.section_viewer.current_index,
    )
    self.section_viewer.set_overlay(arr)
```

Add `set_overlay(arr)` to `SectionViewer` — it calls `self._image.setImage(arr.T, levels=...)` exactly like raw amplitude, but tracks an "overlay active" flag for `View → Show Source` toggle.

## Step 7: New Plugin template

```python
# src/eggseis/plugin_template.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from eggseis.plugin_loader import USER_PLUGIN_DIR

TEMPLATE = '''\
"""User plugin: {name}.

Drop this file in {dir}/ and restart eggseis.
"""

from __future__ import annotations

import numpy as np

from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="{display}", version="0.1.0")
def {func}(
    trace: np.ndarray,
    gain: float = Param(1.0, label="Gain", min=0.0, max=10.0),
) -> np.ndarray:
    return (trace * gain).astype(np.float32)
'''


def create_template(name: str) -> Path:
    USER_PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    func = name.lower().replace(" ", "_").replace("-", "_")
    target = USER_PLUGIN_DIR / f"{func}.py"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(TEMPLATE.format(
        name=name, dir=USER_PLUGIN_DIR, display=name, func=func,
    ))
    return target


def open_in_editor(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])
```

In the menu handler:

```python
def _new_plugin_from_template(self) -> None:
    name, ok = QInputDialog.getText(self, "New Plugin", "Name:")
    if not ok or not name.strip():
        return
    path = create_template(name.strip())
    open_in_editor(path)
    QMessageBox.information(
        self, "Plugin created",
        f"Wrote {path}\nRestart eggseis to register it.",
    )
```

Hot-reload is tempting; defer it. Restart is fine for M3 and removes a class of "stale module" bugs.

## Step 8: Tests

### 8a — decorator + schema

```python
# tests/test_plugin_decorator.py
import numpy as np
from eggseis.plugin import Param, clear_registry, registered, trace_attribute


def test_decorator_builds_param_model():
    clear_registry()

    @trace_attribute(name="Gain")
    def gain(trace, k: float = Param(2.0, min=0.0, max=10.0)):
        return trace * k

    specs = [s for s in registered() if s.func is gain]
    assert len(specs) == 1
    spec = specs[0]
    model = spec.param_model()
    assert model.k == 2.0
    # bounds enforced
    import pytest
    with pytest.raises(Exception):
        spec.param_model(k=99.0)
```

### 8b — discovery

```python
# tests/test_plugin_loader.py
def test_user_plugins_load_from_directory(tmp_path, monkeypatch):
    plugin_file = tmp_path / "myplug.py"
    plugin_file.write_text(
        "import numpy as np\n"
        "from eggseis.plugin import Param, trace_attribute\n"
        "@trace_attribute(name='MyPlug')\n"
        "def myplug(trace, k: float = Param(1.5)):\n"
        "    return trace * k\n"
    )
    from eggseis.plugin import clear_registry, registered
    from eggseis.plugin_loader import load_user_plugins
    clear_registry()
    loaded = load_user_plugins(tmp_path)
    assert plugin_file in loaded
    names = [s.name for s in registered()]
    assert "MyPlug" in names
```

### 8c — runner

```python
# tests/test_plugin_runner.py
def test_envelope_matches_scipy(sample_volume):
    from eggseis.builtins.envelope import envelope
    from eggseis.plugin_runner import run_on_section

    spec = envelope._eggseis_spec
    out = run_on_section(spec, spec.param_model(), sample_volume, "inline", sample_volume.geometry.inline_min)
    assert out.shape == (sample_volume.geometry.n_xlines, sample_volume.geometry.n_samples)
    assert (out >= 0).all()
```

### 8d — GUI smoke

Extend `tests/test_gui_smoke.py`:

```python
def test_apply_builtin_attribute(qtbot, demo_project_path):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project(demo_project_path)
    qtbot.waitUntil(lambda: win.tree.topLevelItemCount() > 0)

    # open survey
    survey_item = win.tree.topLevelItem(0).child(0).child(0)
    win.tree.itemDoubleClicked.emit(survey_item, 0)
    qtbot.waitUntil(lambda: win.section_viewer._volume is not None)

    # activate envelope
    from eggseis.builtins.envelope import envelope
    win._activate_attribute(envelope._eggseis_spec)
    qtbot.waitUntil(lambda: win.section_viewer.has_overlay())
```

### Test conventions

- `clear_registry()` in any test that registers plugins, to keep tests isolated.
- `monkeypatch.setattr(plugin_loader, "USER_PLUGIN_DIR", tmp_path)` for any test that touches the user dir.
- No real disk writes outside `tmp_path`.

## Step 9: Docs — `docs/plugin-authoring.md`

This page is M3's product. It is the thing a friend reads to write their first plugin. Keep it short.

Sections:

1. **Hello world.** A 10-line gain plugin. Decorate, save, restart, see it run.
2. **Parameters.** `Param(default, min=, max=, units=, label=)`. Show range/step/choices.
3. **Context dict.** `sample_rate_ms`, `axis`, `index`, `inline`, `xline`.
4. **Vectorized mode.** When/why. One-paragraph example.
5. **Five built-ins as worked examples.** Direct links to the source files.
6. **Where to put it.** `~/.eggseis/plugins/` or an installable package with `eggseis.plugins` entry point.
7. **Troubleshooting.** "It didn't show up" → check stderr. "Slider doesn't move" → wrong type annotation.

The 30-minute test: pick someone who hasn't seen the code. Hand them only this page. If they ship a working plugin in 30 minutes, the API is right.

## Step 10: CLI

Add `eggseis plugins` for headless inspection:

```python
@app.command()
def plugins() -> None:
    """List discovered plugins."""
    from eggseis.plugin_loader import discover_all
    for spec in discover_all():
        src = spec.source_path or "(built-in / entry point)"
        typer.echo(f"{spec.name:<28} {spec.id:<40} {src}")
```

Useful for debugging and for CI smoke tests that don't want to spin up Qt.

---

## Execution order

1. Add `pydantic`, `magicgui`, `scipy` to `gui` extra. `pip install -e ".[dev]"`. Smoke test imports.
2. Write `eggseis.plugin` (Param, decorator, registry). Unit tests for decorator → param model.
3. Write `eggseis.builtins.envelope`. Confirm it self-registers.
4. Write `eggseis.plugin_loader` (`load_builtins`, `load_user_plugins`, `load_entry_points`). Tests for each path.
5. Write `eggseis.plugin_runner.run_on_section`. Test against scipy reference for envelope.
6. Add `Attribute` menu + `_activate_attribute` wiring to `MainWindow`. Hard-code envelope first; confirm the painted result looks right against the demo project.
7. Add `ParamDock` (`magicgui`) + `set_overlay` on `SectionViewer`. Wire `paramsChanged → _on_params_changed`.
8. Implement remaining four built-ins. Each should be < 30 lines.
9. Implement `New Plugin…` template + editor launch.
10. Write `docs/plugin-authoring.md`. Hand it to a non-author. Time them. Fix every spot they stall on.
11. Update `tests/test_gui_smoke.py` to cover end-to-end attribute apply.
12. Run `./scripts/test.sh ci` → green on all platforms.

Two or three weekends if you stay disciplined. The trap on this milestone is **paving the cowpath of the future API** — resist adding window-based plugins, async support, or hot-reload. Tier 1 + synchronous + restart-to-register is the contract.

---

## Risks

- **Pydantic ↔ magicgui drift.** magicgui's pydantic support has historically been thin. If it can't render a field cleanly, fall back to building a `magicgui.widgets.Container` from the param spec by hand — keep the registry shape, swap the rendering layer.
- **Parameter dialog re-runs on every keystroke.** `auto_call=True` is fine in M3 with synchronous compute on a trivial inline. If the demo lags, drop to a manual "Apply" button and revisit when M4 lands debounce.
- **Plugin import errors poisoning startup.** Already mitigated — every load path catches and logs, never raises. Add an `Attribute → Reload Plugins` menu in M4 once threading is in.
- **User puts a plugin file with a syntax error in `~/.eggseis/plugins/`.** stderr line is enough for M3. A "Plugin Errors" dock is M4 territory.
- **Determinism flag unused.** `deterministic=True` exists so M4's cache key is meaningful. Don't drop it just because it's not wired up yet.
- **Built-ins are imported from `eggseis.builtins` package.** Make sure each module is referenced from `eggseis/builtins/__init__.py` so the decorators fire. Otherwise discovery silently misses them.
- **Window functions sneaking in.** A user might write a plugin that wants neighbor traces. M3 says no — document it, fail loudly if a function declares a `traces` arg without `vectorized=True`.

---

## Out of scope for M3

- Async / debounce / cancellation / cache → M4.
- Window-based attributes (Tier 2) → v1.1.
- Hot-reload of plugins without restart → M4 or later.
- Plugin marketplace / registry UI → M9.
- Saving the active attribute + parameters into the project file → M5.
- Crossplot inputs (attribute as a column) → M7.
- Volume-applied attributes → still trace-local in M3; volume-wide compute is M6 territory.

---

## When M3 is done

A clean exit looks like:

- `eggseis gui examples/demo-project` opens, shows the section, the `Attribute` menu lists 5 built-ins.
- Selecting `Envelope` paints the section with envelope amplitudes; toggling `View → Show Source` restores raw.
- `File → New Plugin…` writes a working file under `~/.eggseis/plugins/`, opens the editor; restart picks it up.
- `eggseis plugins` lists everything from CLI.
- One non-author wrote a plugin in under 30 minutes following `docs/plugin-authoring.md`.
- Headless tests cover decorator, loader, runner, and one end-to-end GUI flow on Linux/macOS/Windows.
- README updated with a new screenshot showing an attribute applied. CHANGELOG entry under `[v0.1.0a3]`.
- Tag `v0.1.0a3` on `main` after the M3 PR merges.
- Take a beat. Then start M4 — "The compute feels good."
