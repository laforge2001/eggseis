# eggseis — agent notes

## Environment
- Python venv at `.venv/`. Activate before any `pip` or `pytest`: `source .venv/bin/activate`.
- Qt runs headless via `QT_QPA_PLATFORM=offscreen`. The test runner sets this; outside it, set it manually.

## Commands (prefer over raw pytest)
- `./scripts/test.sh ci` — lint + full test suite (mirrors GitHub Actions). Default invocation.
- `./scripts/test.sh demo` — launch GUI against `examples/demo-project/`.
- `./scripts/test.sh shot` — regenerate `docs/m2-screenshot.png`.
- `./scripts/test.sh hooks` — enable `.githooks/` for screenshot auto-refresh.
- `./scripts/test.sh setup` — `pip install -e ".[dev]"`.
- `eggseis plugins [--params]` — list discovered plugins + source paths (debug discovery).

## Project layout
- `src/eggseis/` — library (data, backends, viewers, widgets, app, cli, axes, colormaps, project, plugin, plugin_loader, plugin_runner, plugin_template, builtins/).
- `tests/` — pytest. `test_gui_smoke.py` uses `pytest-qt` + offscreen.
- `examples/demo-project/` — checked-in project for demo + screenshot.
- `~/.eggseis/plugins/` — default user-plugin dir. Override/extend with `$EGGSEIS_PLUGIN_PATH` (os.pathsep-separated). Resolution: `$EGGSEIS_PLUGIN_PATH` entries → default user dir → `eggseis.plugins` entry points.
- Per-milestone plans: `M1-PLAN.md`, `M2-PLAN.md`, `M3-PLAN.md`. Master roadmap: `ROADMAP.md`.
- Plugin authoring reference: `docs/plugin-authoring.md`.

## Conventions
- Axis names live in `eggseis.axes.Axis` (StrEnum). Never re-declare `("inline","xline","timeslice")` inline.
- Coordinate math goes on `SurveyGeometry` (`inline_at`, `xline_at`, `time_at`, `range_for`), not in viewer/widget code.
- GUI deps gated behind the `gui` pyproject extra; library install stays slim.
- Qt tests use `qtbot.waitSignal` / `qtbot.waitUntil` — never `time.sleep`. No cross-OS pixel-exact asserts.
- Ruff per-file ignores documented in `pyproject.toml`: `B008` for typer defaults, `N815` for Qt signal names.
- Plugins always declare params via `Param(...)` defaults; bare defaults raise at decoration time. `accepts_context=True` flag set automatically when the function declares a `context` arg.
- Plugin tests must `clear_registry()` (autouse fixture pattern) since `_REGISTRY` is process-global.

## Workflow
- Branch protection on `main` requires PR review — CLI `gh pr merge` is blocked without `--admin`. Don't bypass without explicit user OK.
- On milestone completion, follow the wrap-up rule (see memory): audit ROADMAP exit criteria → CHANGELOG entry → README status → next-milestone issue + branch → tag after merge.
- Pre-commit hook in `.githooks/pre-commit` auto-refreshes the M2 screenshot when UI sources are staged. Enable per-clone via `./scripts/test.sh hooks`.
- **GUI screenshot rule:** any substantial GUI change MUST regenerate `docs/m2-screenshot.png` before commit. Run `./scripts/test.sh shot` and stage the PNG alongside the source change. Don't rely on the pre-commit hook — verify the screenshot reflects the new state. Substantial = new dock, new menu, layout shift, new widget, anything visible from the rendered window.

## Dev doc
- `docs/development.md` — local workflow, headless mechanics, shortcuts, troubleshooting. Cross-link from any new contributor-facing change.
