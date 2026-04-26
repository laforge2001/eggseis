#!/usr/bin/env bash
# eggseis test runner — wraps the local dev workflow.
#
# Usage:
#   scripts/test.sh [command] [extra pytest args...]
#
# Commands:
#   setup     install package + dev extras into the active env
#   lint      ruff check .
#   test      run the full pytest suite headlessly (default)
#   gui       run only the GUI smoke tests headlessly
#   nogui     run everything except the GUI smoke tests
#   demo      launch the eggseis GUI against examples/demo-project/
#   shot      regenerate docs/m2-screenshot.png from the demo project
#   hooks     point git at .githooks/ so the screenshot auto-regenerates
#   ci        lint + full headless suite (mirrors GitHub Actions)
#   help      print this message

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Auto-activate .venv if present and nothing else is active.
if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

cmd="${1:-test}"
shift || true

print_help() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
}

case "$cmd" in
    setup)
        pip install -e ".[dev]"
        ;;
    lint)
        ruff check .
        ;;
    test|all)
        QT_QPA_PLATFORM=offscreen pytest "$@"
        ;;
    gui)
        QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py -v "$@"
        ;;
    nogui)
        pytest --ignore=tests/test_gui_smoke.py "$@"
        ;;
    demo)
        eggseis gui examples/demo-project "$@"
        ;;
    shot)
        python scripts/screenshot.py "$@"
        ;;
    hooks)
        git config core.hooksPath .githooks
        echo "git hooks now resolve from .githooks/"
        ;;
    ci)
        ruff check .
        QT_QPA_PLATFORM=offscreen pytest
        ;;
    help|-h|--help)
        print_help
        ;;
    *)
        echo "unknown command: $cmd" >&2
        echo
        print_help
        exit 1
        ;;
esac
