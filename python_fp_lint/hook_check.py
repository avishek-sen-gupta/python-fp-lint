# python_fp_lint/hook_check.py
"""Core logic for the PreToolUse lint gate hook.

Extracted from the shell hook so it can be unit-tested without any subprocess
or environment setup. The shell hook (hooks/lint-check.sh) becomes a thin
wrapper that just checks the lock file and pipes stdin here.
"""

import json
import os
import sys
import tempfile

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.result import LintViolation


def simulate_edit(
    content: str, old_string: str, new_string: str, replace_all: bool
) -> tuple[str, int, int] | None:
    """Simulate an Edit tool call against existing file content.

    Returns (post_edit_content, start_line, end_line) where the line range is
    the region of the post-edit file that was touched, or None if old_string
    is not found in content.
    """
    if old_string not in content:
        return None
    if replace_all:
        result = content.replace(old_string, new_string)
        end_line = max(1, result.count("\n") + 1)
        return result, 1, end_line
    start_line = content[: content.index(old_string)].count("\n") + 1
    new_line_count = max(1, new_string.count("\n") + 1)
    end_line = start_line + new_line_count - 1
    result = content.replace(old_string, new_string, 1)
    return result, start_line, end_line


def violations_in_range(
    violations: list[LintViolation], start: int, end: int
) -> list[LintViolation]:
    """Return only violations whose line falls within [start, end]."""
    return [v for v in violations if start <= v.line <= end]


def check_tool_event(tool_name: str, tool_input: dict) -> int:
    """Evaluate a PreToolUse event. Returns 0 (allow) or 2 (block).

    Prints a diagnostic to stderr when blocking.
    """
    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        if not file_path or not file_path.endswith(".py"):
            return 0
        if not os.path.isfile(file_path):
            return 0
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return 0
        outcome = simulate_edit(
            content,
            tool_input.get("old_string", ""),
            tool_input.get("new_string", ""),
            tool_input.get("replace_all", False),
        )
        if outcome is None:
            return 0
        post_content, start_line, end_line = outcome

    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if not file_path or not file_path.endswith(".py"):
            return 0
        post_content = tool_input.get("content", "")
        start_line = 1
        end_line = max(1, post_content.count("\n") + 1)

    else:
        return 0

    fd, tmpfile = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(post_content)
        lint_result = LintGate().evaluate([tmpfile], os.getcwd())
        in_range = violations_in_range(lint_result.violations, start_line, end_line)
    finally:
        os.unlink(tmpfile)

    if not in_range:
        return 0

    count = len(in_range)
    print(
        f"[lint-gate] Blocked: {count} FP violation(s) in edited range "
        f"(lines {start_line}-{end_line}) of {file_path}",
        file=sys.stderr,
    )
    for v in in_range:
        print(f"  {v.rule}:{v.line}:{v.message}", file=sys.stderr)
    print(
        "\nFix the violations or disable the lint gate with /lint off", file=sys.stderr
    )
    return 2


def main():
    """Entry point: python -m python_fp_lint hook-check < event.json"""
    data = json.load(sys.stdin)
    sys.exit(check_tool_event(data.get("tool_name", ""), data.get("tool_input", {})))
