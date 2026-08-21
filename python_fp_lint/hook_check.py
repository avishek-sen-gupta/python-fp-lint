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


def _lint_content(
    gate: LintGate, content: str, start_line: int, end_line: int
) -> list[LintViolation]:
    """Lint post-edit content off a temp file, keeping only the edited range."""
    fd, tmpfile = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        result = gate.evaluate([tmpfile], os.getcwd())
    finally:
        os.unlink(tmpfile)
    return violations_in_range(result.violations, start_line, end_line)


def _edit_outcome(tool_input: dict) -> tuple[str, int, int] | None:
    """Post-edit content and touched line range for an Edit event."""
    file_path = tool_input.get("file_path", "")
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    return simulate_edit(
        content,
        tool_input.get("old_string", ""),
        tool_input.get("new_string", ""),
        tool_input.get("replace_all", False),
    )


def _write_outcome(tool_input: dict) -> tuple[str, int, int] | None:
    """Post-write content and touched line range for a Write event: all of it."""
    content = tool_input.get("content", "")
    return content, 1, max(1, content.count("\n") + 1)


_OUTCOME_BY_TOOL = {"Edit": _edit_outcome, "Write": _write_outcome}


def _report_block(
    file_path: str, start_line: int, end_line: int, violations: list[LintViolation]
) -> None:
    print(
        f"[lint-gate] Blocked: {len(violations)} FP violation(s) in edited range "
        f"(lines {start_line}-{end_line}) of {file_path}",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  {v.rule}:{v.line}:{v.message}", file=sys.stderr)
    print(
        "\nFix the violations or disable the lint gate with /lint off", file=sys.stderr
    )


def check_tool_event(
    tool_name: str, tool_input: dict, config_path: str | None = None
) -> int:
    """Evaluate a PreToolUse event. Returns 0 (allow) or 2 (block).

    Prints a diagnostic to stderr when blocking.
    """
    outcome_of = _OUTCOME_BY_TOOL.get(tool_name)
    file_path = tool_input.get("file_path", "")
    if outcome_of is None or not file_path.endswith(".py"):
        return 0

    gate = LintGate(config_path=config_path)
    # The edit is judged by where the real file lives, not by the temp copy
    # that gets linted.
    if gate.is_excluded(file_path, os.getcwd()):
        return 0

    outcome = outcome_of(tool_input)
    if outcome is None:
        return 0
    post_content, start_line, end_line = outcome

    in_range = _lint_content(gate, post_content, start_line, end_line)
    if not in_range:
        return 0

    _report_block(file_path, start_line, end_line, in_range)
    return 2


def main(config_path: str | None = None):
    """Entry point: python -m python_fp_lint hook-check < event.json

    Unlike `check` and `precommit`, config is optional here: the Claude Code
    gate has to work the moment the hook is installed, so no config means
    built-in defaults.
    """
    data = json.load(sys.stdin)
    sys.exit(
        check_tool_event(
            data.get("tool_name", ""), data.get("tool_input", {}), config_path
        )
    )
