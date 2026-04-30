# Writing eggseis plugins

This page is the authoritative reference for the M3 plugin API. If a friend can
read it cold and ship a working plugin in 30 minutes, the API is right.

## TL;DR

A plugin is a Python function decorated with `@trace_attribute`:

```python
import numpy as np
from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="Gain", version="0.1.0")
def gain(
    trace: np.ndarray,
    k: float = Param(1.0, label="Gain factor", min=0.0, max=10.0),
) -> np.ndarray:
    return (trace * k).astype(np.float32)
```

Drop it in `~/.eggseis/plugins/gain.py`, restart `eggseis gui`, pick it from the
**Attribute** menu. Every `Param(...)` becomes a slider in the **Parameters**
dock automatically.

## Where plugins live

eggseis discovers plugins from three sources, in order:

1. **Built-ins** — `src/eggseis/builtins/`. Always loaded.
2. **`$EGGSEIS_PLUGIN_PATH`** — `os.pathsep`-separated list of directories
   (`:` on macOS/Linux, `;` on Windows). Scanned left to right.
3. **`~/.eggseis/plugins/`** — the default user directory.
4. **Entry points** — any installed package that declares a
   `eggseis.plugins` entry point group.

Duplicates (same resolved directory) are dropped; first occurrence wins.
Filenames starting with `_` are skipped. Subdirectories are ignored — the scan
is **flat, not recursive**.

```bash
# per-project plugin folder
cd /path/to/project
EGGSEIS_PLUGIN_PATH=./plugins eggseis gui .

# multiple sources
export EGGSEIS_PLUGIN_PATH="$HOME/work/proj-plugins:/srv/team/plugins"
```

To inspect what was discovered:

```bash
eggseis plugins              # name, version, source path
eggseis plugins --params     # adds parameter declarations
```

## Function shape

A trace-local plugin receives one trace at a time:

```python
def my_attr(trace: np.ndarray, *, [params]) -> np.ndarray: ...
```

- `trace` — 1D `np.ndarray`, shape `(n_samples,)`. The framework iterates
  every trace in the visible section and assembles the output.
- Return shape must equal `trace.shape`. Ideally cast to `np.float32` for
  consistency.

If you need geometry information, declare a `context: dict` arg:

```python
def my_attr(trace: np.ndarray, context: dict, *, [params]) -> np.ndarray: ...
```

`context` carries `sample_rate_ms`, `axis` (`"inline"` / `"xline"` /
`"timeslice"`), `index`. Trace-local plugins on a timeslice are no-ops by
design — the runner returns the source slice unchanged.

## Parameter declarations

Every keyword argument **must** declare a `Param(...)` default. Plain defaults
(`k=1.0`) raise `TypeError` at import time — by intention, since the GUI
needs the metadata.

```python
Param(default,
      label=None,        # display label; falls back to the arg name
      min=None,          # numeric lower bound (slider lo)
      max=None,          # numeric upper bound (slider hi)
      step=None,         # spinbox step; for FloatSlider, defaults to (max-min)/1000
      units=None,        # string shown as a tooltip
      description=None,  # long-form help (planned: hover help)
      choices=None,      # tuple of values → renders as dropdown
)
```

### Widget rules

| Param shape                                | Widget          |
|--------------------------------------------|-----------------|
| `Param(1.0, min=0.0, max=10.0)`            | `FloatSlider`   |
| `Param(21, min=3, max=501, step=2)`        | `Slider` (int)  |
| `Param(0.05)` (no bounds)                  | `FloatSpinBox`  |
| `Param("hilbert", choices=("hilbert","fft"))` | dropdown    |
| `Param(True)`                              | `CheckBox`      |

Float sliders without an explicit `step` get a smooth one (`(max-min)/1000`).
Bound a parameter on both sides if you want a slider — otherwise you'll get
a spinbox.

## Decorator options

```python
@trace_attribute(
    name=None,           # display name (default: snake_case → Title Case)
    version="0.1.0",     # plugin version, used in cache keys later (M4)
    vectorized=False,    # see below
    deterministic=True,  # affects cache eligibility in M4
)
```

### Vectorized plugins

Default mode runs your function once per trace. For SciPy operations that
naturally take 2D input, opt in:

```python
@trace_attribute(name="Gain (Vec)", vectorized=True)
def gain_vec(traces: np.ndarray, k: float = Param(1.0, min=0.0, max=10.0)):
    return (traces * k).astype(np.float32)
```

- First arg renames `trace` → `traces`.
- Shape is `(n_traces, n_samples)`.
- Return same shape.
- One call per slice, not one per trace.

Use this when scipy / numpy can vectorize over the trace axis (filtering,
hilbert with `axis=-1`, FFT). Skip it when each trace needs different work.

## Built-in examples

All five live in `src/eggseis/builtins/`. Read them as worked examples:

- `envelope.py` — minimal, no params (`np.abs(hilbert(trace))`).
- `instantaneous_phase.py` — minimal, no params.
- `instantaneous_frequency.py` — uses `context["sample_rate_ms"]`.
- `rms_amplitude.py` — single integer param + sliding window.
- `ormsby_bandpass.py` — three params, defensive bounds clamping.

`Clip` and `Gain` examples ship in `~/.eggseis/plugins/` if you followed the
walkthrough.

## File → New Plugin…

In the GUI, **File → New Plugin…**:

1. Prompts for a display name.
2. Writes `~/.eggseis/plugins/<slug>.py` with a working starter (a simple
   gain plugin — edit it).
3. Opens the file in your OS default editor.
4. Restart eggseis to pick up the change.

Cancel-able at any step. If a file with that slug already exists, you'll see
a warning and nothing is overwritten.

## Recompute model in M3

- Synchronous on the GUI thread.
- Slider drag re-runs the plugin on every value change (no debounce yet).
- Slice change (axis/index) re-runs.
- Errors from your plugin land in the **status bar** for 5 seconds; the last
  good overlay stays visible.

Threading, debounce, cancellation, and the in-memory LRU cache land in M4.
Don't pre-optimize for them in your plugin code.

## Common pitfalls

**Plugin doesn't appear in the menu.** Check:
- `eggseis plugins` lists it.
- File is directly under a scanned directory (not nested).
- Filename does not start with `_`.
- No syntax errors — loader logs a stderr line like
  `eggseis: failed to load plugin <path>: <error>`.

**Slider feels too coarse.** Set `step=` on the Param, or rely on the
auto-derived `(max-min)/1000` for floats with both bounds.

**Plugin output range very different from raw (e.g. envelope is non-negative).**
By default `View → Lock Levels to Raw` is **on**, which paints overlays against
the raw slice's percentile range so amplitude-changing plugins (gain, clip)
behave intuitively. For plugins whose output lives on a different scale
(envelope, instantaneous frequency), turn this off to let the viewer
auto-stretch the overlay.

**`filtfilt` raises `ValueError: padlen ...`.** Your filter taps exceed
`(n_samples - 1) / 3`. Clamp `n_taps` and pass an explicit
`padlen=min(3*n - 1, n_samples - 1)` (see `ormsby_bandpass.py`).

**Plugin file imports something Python can't find at startup.** The loader
prints to stderr and continues. Check the terminal you launched
`eggseis gui` from.

## Distributing as a package

Skip `~/.eggseis/plugins/` and ship via `pip` instead:

```toml
# pyproject.toml of your distribution
[project.entry-points."eggseis.plugins"]
my_attrs = "my_package.attrs"
```

Anything imported by `my_package.attrs` (which should call
`@trace_attribute`) is registered when eggseis starts.

## Out of scope for M3

- Window-based plugins (look at neighbor traces) → v1.1.
- Multi-input / DAG plugins → M6 (graph milestone).
- Hot reload without restart → likely M4.
- Saving the active plugin + parameters into the project file → M5.

## Quick reference card

```python
from __future__ import annotations
import numpy as np
from eggseis.plugin import Param, trace_attribute


@trace_attribute(name="Display Name", version="0.1.0")
def my_attr(
    trace: np.ndarray,
    context: dict,                              # optional, declare if needed
    pct: float = Param(99.0, label="Percentile", min=50.0, max=100.0),
    win: int = Param(21, label="Window", min=3, max=501, step=2),
) -> np.ndarray:
    fs = 1000.0 / context["sample_rate_ms"]    # via context
    out = ...                                  # your work here
    return out.astype(np.float32)
```

## Determinism and caching

By default, plugins are `deterministic=True`, which means a given plugin +
parameters + slice combination always produces the same bytes. Eggseis caches
those results in memory and reuses them when the user pans back.

If your plugin reads a clock, calls an RNG, or otherwise produces different
output for identical inputs, mark it as non-deterministic so it is never
cached:

```python
@trace_attribute(name="My Random Filter", deterministic=False)
def my_random(trace, gain: float = Param(1.0)):
    ...
```

> **In a pipeline:** a `deterministic=False` node poisons every node
> downstream of itself for caching purposes. The plugin still runs;
> outputs are simply never memoised, so revisiting the same params
> and slice always recomputes. Prefer `deterministic=True` whenever
> your plugin's output is a pure function of its input and parameters.

## Multi-input plugins (M6+)

`@trace_attribute` is the single-input shorthand. For plugins that take
two or more named input arrays — e.g. `subtract(a, b)` — use
`@graph_node`:

```python
import numpy as np
from eggseis.plugin import graph_node

@graph_node(name="Subtract", version="0.1.0", inputs=("a", "b"))
def subtract(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a - b
```

- Each name in `inputs` must match a positional or keyword argument
  of the function. Those arguments receive `np.ndarray` values, one
  per port, sliced consistently along the trace axis.
- Non-input arguments still need a `Param(...)` default.
- An optional `context` arg works exactly as with `@trace_attribute`.
- The function's return value is emitted on the single output port
  `"out"`. Multiple outputs per node are deferred to v1.1.
- `vectorized=True` is single-input only — multi-input plugins run
  one row at a time. If you need vectorisation, restructure into
  separate single-input attributes plus a downstream combiner.

In the GUI, the canvas renders one input port circle per name in
`inputs`. Wires must land on each of them before the node can run;
an unconnected input emits a clear error message via the executor's
`failed` signal.

**Disabling a multi-input node is not allowed.** Identity-skip is only
well-defined when there is one upstream array to forward through.
Remove the node instead.
