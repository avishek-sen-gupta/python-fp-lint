#!/bin/sh
# lint-check.sh — PreToolUse hook: block Edit/Write if new FP lint violations are introduced.
# Simulates the edit on a temp file, runs python-fp-lint, diffs violations.
# Exit 0 = allow, Exit 2 = block.

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/lib/hash.sh"

LOCK="/tmp/ctx-lint/$(project_hash "$PWD")"

# Lint gate off — nothing to do
[ -f "$LOCK" ] || exit 0

# python-fp-lint must be available
LINT_CMD=""
VENV_PYTHON="$HOOK_DIR/../venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    LINT_CMD="$VENV_PYTHON -m python_fp_lint"
elif python3 -m python_fp_lint --help >/dev/null 2>&1; then
    LINT_CMD="python3 -m python_fp_lint"
fi
[ -n "$LINT_CMD" ] || exit 0

# Read stdin (tool event JSON)
INPUT=$(cat)

# Extract tool name
TOOL=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

case "$TOOL" in
  Edit|Write) ;;
  *) exit 0 ;;
esac

# --- Extract file path and compute simulated content ---
if [ "$TOOL" = "Edit" ]; then
    REAL_FILE=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)
    [ -n "$REAL_FILE" ] || exit 0
    [ -f "$REAL_FILE" ] || exit 0

    # Simulate the edit: apply old_string → new_string replacement
    SIMULATED=$(printf '%s' "$INPUT" | python3 -c "
import sys, json

data = json.load(sys.stdin)
inp = data.get('tool_input', {})
file_path = inp.get('file_path', '')
old_string = inp.get('old_string', '')
new_string = inp.get('new_string', '')
replace_all = inp.get('replace_all', False)

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
except Exception:
    sys.exit(0)

if replace_all:
    result = content.replace(old_string, new_string)
else:
    if old_string not in content:
        sys.exit(0)
    result = content.replace(old_string, new_string, 1)

sys.stdout.write(result)
" 2>/dev/null)
    SIM_EXIT=$?
    [ $SIM_EXIT -eq 0 ] || exit 0

elif [ "$TOOL" = "Write" ]; then
    REAL_FILE=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)
    [ -n "$REAL_FILE" ] || exit 0

    SIMULATED=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
sys.stdout.write(d.get('tool_input', {}).get('content', ''))
" 2>/dev/null)
fi

# Only lint Python files
case "$REAL_FILE" in
    *.py) ;;
    *) exit 0 ;;
esac

# Create temp file with simulated content
TMPFILE=$(mktemp /tmp/lint-check-XXXXXX.py)
trap 'rm -f "$TMPFILE"' EXIT

printf '%s' "$SIMULATED" > "$TMPFILE"

# --- Run lint on the pre-edit (real) file ---
PRE_VIOLATIONS=$(cd "$PWD" && $LINT_CMD --format json check "$REAL_FILE" 2>/dev/null \
    | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for v in data.get('violations', []):
        print(v.get('rule','') + ':' + str(v.get('line','')) + ':' + v.get('message',''))
except Exception:
    pass
" 2>/dev/null)

# --- Run lint on the post-edit (temp) file ---
POST_VIOLATIONS_RAW=$(cd "$PWD" && $LINT_CMD --format json check "$TMPFILE" 2>/dev/null \
    | python3 -c "
import sys, json, os
real = sys.argv[1]
tmp = sys.argv[2]
try:
    data = json.load(sys.stdin)
    for v in data.get('violations', []):
        # normalise path back to real file
        rule = v.get('rule','')
        line = str(v.get('line',''))
        msg = v.get('message','')
        fpath = v.get('file','').replace(tmp, real)
        print(rule + ':' + line + ':' + msg)
except Exception:
    pass
" "$REAL_FILE" "$TMPFILE" 2>/dev/null)

# --- Diff: find violations in POST that aren't in PRE ---
NEW_VIOLATIONS=$(python3 -c "
import sys
pre = set(sys.argv[1].strip().splitlines()) if sys.argv[1].strip() else set()
post = set(sys.argv[2].strip().splitlines()) if sys.argv[2].strip() else set()
new = post - pre
for v in sorted(new):
    print(v)
" "$PRE_VIOLATIONS" "$POST_VIOLATIONS_RAW" 2>/dev/null)

# --- Block if new violations found ---
if [ -n "$NEW_VIOLATIONS" ]; then
    COUNT=$(printf '%s\n' "$NEW_VIOLATIONS" | wc -l | tr -d ' ')
    printf '[lint-gate] Blocked: %d new FP violation(s) in %s\n\n' "$COUNT" "$REAL_FILE" >&2
    printf '%s\n' "$NEW_VIOLATIONS" | while IFS= read -r line; do
        printf '  %s\n' "$line" >&2
    done
    printf '\nFix the violations or disable the lint gate with /lint off\n' >&2
    exit 2
fi

exit 0
