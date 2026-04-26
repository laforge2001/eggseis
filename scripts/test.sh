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
#   visible   run GUI tests with real Qt windows (no offscreen platform)
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
    visible)
        pytest tests/test_gui_smoke.py -v "$@"
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
