#!/bin/sh
# lint-check.sh — PreToolUse hook: block Edit/Write if FP lint violations fall in the edited line range.
# Exit 0 = allow, Exit 2 = block.

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/lib/hash.sh"

LOCK="/tmp/ctx-lint/$(project_hash "$PWD")"

# Lint gate off — nothing to do
[ -f "$LOCK" ] || exit 0

# python-fp-lint must be available
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

# Read stdin (tool event JSON)
INPUT=$(cat)

# Extract tool name
TOOL=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

case "$TOOL" in
  Edit|Write) ;;
  *) exit 0 ;;
esac

# Create temp files — use a subdir so the .py file has the right extension
# (macOS mktemp requires the template to end with X's, so .py suffix is invalid)
TMPDIR=$(mktemp -d /tmp/lint-check-XXXXXX)
TMPFILE="$TMPDIR/check.py"
RANGEFILE=$(mktemp /tmp/lint-range-XXXXXX)
trap 'rm -rf "$TMPDIR" "$RANGEFILE"' EXIT

# --- Simulate edit and compute edited line range ---
if [ "$TOOL" = "Edit" ]; then
    REAL_FILE=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)
    [ -n "$REAL_FILE" ] || exit 0
    [ -f "$REAL_FILE" ] || exit 0

    printf '%s' "$INPUT" | python3 -c "
import sys, json

data = json.load(sys.stdin)
inp = data.get('tool_input', {})
file_path = inp.get('file_path', '')
old_string = inp.get('old_string', '')
new_string = inp.get('new_string', '')
replace_all = inp.get('replace_all', False)
range_file = sys.argv[1]
out_file = sys.argv[2]

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
except Exception:
    sys.exit(0)

if old_string not in content:
    sys.exit(0)

if replace_all:
    result = content.replace(old_string, new_string)
    # Whole file may be affected — use full range
    end_line = max(1, result.count('\n') + 1)
    start_line = 1
else:
    # Start line = line where old_string begins in original
    start_line = content[:content.index(old_string)].count('\n') + 1
    new_line_count = max(1, new_string.count('\n') + 1)
    end_line = start_line + new_line_count - 1
    result = content.replace(old_string, new_string, 1)

with open(out_file, 'w', encoding='utf-8') as f:
    f.write(result)

with open(range_file, 'w') as f:
    f.write(f'{start_line} {end_line}\n')
" "$RANGEFILE" "$TMPFILE" 2>/dev/null || exit 0

elif [ "$TOOL" = "Write" ]; then
    REAL_FILE=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)
    [ -n "$REAL_FILE" ] || exit 0

    printf '%s' "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
content = data.get('tool_input', {}).get('content', '')
out_file = sys.argv[1]
range_file = sys.argv[2]

with open(out_file, 'w', encoding='utf-8') as f:
    f.write(content)

end_line = max(1, content.count('\n') + 1)
with open(range_file, 'w') as f:
    f.write(f'1 {end_line}\n')
" "$TMPFILE" "$RANGEFILE" 2>/dev/null || exit 0
fi

# Only lint Python files
case "$REAL_FILE" in
    *.py) ;;
    *) exit 0 ;;
esac

[ -f "$RANGEFILE" ] || exit 0
read START_LINE END_LINE < "$RANGEFILE"

# --- Run lint on post-edit file, filter to edited line range ---
NEW_VIOLATIONS=$(cd "$PWD" && $LINT_CMD --format json check "$TMPFILE" 2>/dev/null \
    | python3 -c "
import sys, json
real = sys.argv[1]
start = int(sys.argv[2])
end = int(sys.argv[3])
try:
    data = json.load(sys.stdin)
    for v in data.get('violations', []):
        line = v.get('line', 0)
        if start <= line <= end:
            print(v.get('rule','') + ':' + str(line) + ':' + v.get('message',''))
except Exception:
    pass
" "$REAL_FILE" "$START_LINE" "$END_LINE" 2>/dev/null)

# --- Block if violations found in edited range ---
if [ -n "$NEW_VIOLATIONS" ]; then
    COUNT=$(printf '%s\n' "$NEW_VIOLATIONS" | wc -l | tr -d ' ')
    printf '[lint-gate] Blocked: %d FP violation(s) in edited range (lines %s-%s) of %s\n\n' \
        "$COUNT" "$START_LINE" "$END_LINE" "$REAL_FILE" >&2
    printf '%s\n' "$NEW_VIOLATIONS" | while IFS= read -r line; do
        printf '  %s\n' "$line" >&2
    done
    printf '\nFix the violations or disable the lint gate with /lint off\n' >&2
    exit 2
fi

exit 0
