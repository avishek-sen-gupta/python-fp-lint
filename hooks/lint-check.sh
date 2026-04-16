#!/bin/sh
# lint-check.sh — PreToolUse hook: pipes the tool event to python_fp_lint hook-check.
# Exit 0 = allow, Exit 2 = block.
# All line-range filtering logic lives in python_fp_lint/hook_check.py.

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/lib/hash.sh"

LOCK="/tmp/ctx-lint/$(project_hash "$PWD")"

# Lint gate off — nothing to do
[ -f "$LOCK" ] || exit 0

# Locate python_fp_lint
LINT_CMD=""
VENV_PYTHON="$HOOK_DIR/../venv/bin/python"
if [ -n "$PYTHON_FP_LINT_CMD" ]; then
    LINT_CMD="$PYTHON_FP_LINT_CMD"
elif [ -x "$VENV_PYTHON" ]; then
    LINT_CMD="$VENV_PYTHON -m python_fp_lint"
elif python3 -m python_fp_lint --help >/dev/null 2>&1; then
    LINT_CMD="python3 -m python_fp_lint"
fi
[ -n "$LINT_CMD" ] || exit 0

# Delegate everything to Python
cat | $LINT_CMD hook-check
