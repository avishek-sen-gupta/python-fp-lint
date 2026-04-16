"""
Tests for hook_check.py — the PreToolUse lint gate logic.

All tests are pure Python: no subprocess, no shell, no environment setup.
"""

import shutil

import pytest

from python_fp_lint.hook_check import (
    check_tool_event,
    simulate_edit,
    violations_in_range,
)
from python_fp_lint.result import LintViolation

needs_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed",
)


class TestSimulateEdit:
    def test_single_line_replacement(self):
        content = "x = 1\n# PLACEHOLDER\ny = 2\n"
        result, start, end = simulate_edit(content, "# PLACEHOLDER", "import os", False)
        assert result == "x = 1\nimport os\ny = 2\n"
        assert start == 2
        assert end == 2

    def test_multiline_new_string_expands_end(self):
        content = "x = 1\n# PLACEHOLDER\ny = 2\n"
        _, start, end = simulate_edit(content, "# PLACEHOLDER", "# a\n# b", False)
        assert start == 2
        assert end == 3

    def test_replace_at_first_line(self):
        content = "# PLACEHOLDER\nx = 1\n"
        _, start, end = simulate_edit(content, "# PLACEHOLDER", "import os", False)
        assert start == 1
        assert end == 1

    def test_replace_all_covers_full_file(self):
        content = "# A\nx = 1\n# A\n"
        result, start, end = simulate_edit(content, "# A", "y = 2", True)
        assert start == 1
        assert end == max(1, result.count("\n") + 1)

    def test_old_string_not_found_returns_none(self):
        assert simulate_edit("x = 1\n", "NOTFOUND", "y = 2", False) is None

    def test_single_line_file_no_newline(self):
        content = "# PLACEHOLDER"
        result, start, end = simulate_edit(content, "# PLACEHOLDER", "import os", False)
        assert start == 1
        assert end == 1
        assert result == "import os"


class TestViolationsInRange:
    def _v(self, line: int) -> LintViolation:
        return LintViolation(rule="F401", file="f.py", line=line, message="unused")

    def test_includes_both_boundaries(self):
        vs = [self._v(1), self._v(2), self._v(3)]
        assert violations_in_range(vs, 2, 3) == [vs[1], vs[2]]

    def test_excludes_outside_range(self):
        vs = [self._v(1), self._v(5)]
        assert violations_in_range(vs, 2, 4) == []

    def test_single_line_range(self):
        vs = [self._v(1), self._v(2), self._v(3)]
        assert violations_in_range(vs, 2, 2) == [vs[1]]

    def test_empty_violations(self):
        assert violations_in_range([], 1, 10) == []


@needs_ruff
class TestCheckToolEvent:
    def test_violation_in_edit_range_is_blocked(self, tmp_path):
        f = tmp_path / "s.py"
        f.write_text("x = 1\n# PLACEHOLDER\ny = 2\n")
        rc = check_tool_event(
            "Edit",
            {
                "file_path": str(f),
                "old_string": "# PLACEHOLDER",
                "new_string": "import os",  # F401
                "replace_all": False,
            },
        )
        assert rc == 2

    def test_clean_edit_is_allowed(self, tmp_path):
        f = tmp_path / "s.py"
        f.write_text("x = 1\n# PLACEHOLDER\ny = 2\n")
        rc = check_tool_event(
            "Edit",
            {
                "file_path": str(f),
                "old_string": "# PLACEHOLDER",
                "new_string": "# clean comment",
                "replace_all": False,
            },
        )
        assert rc == 0

    def test_existing_violation_outside_range_is_allowed(self, tmp_path):
        f = tmp_path / "s.py"
        f.write_text("import os\nx = 1\n# PLACEHOLDER\n")
        rc = check_tool_event(
            "Edit",
            {
                "file_path": str(f),
                "old_string": "# PLACEHOLDER",
                "new_string": "# clean comment",
                "replace_all": False,
            },
        )
        assert rc == 0

    def test_shifted_violation_is_allowed(self, tmp_path):
        """Inserting lines before an existing violation shifts it out of the edit range."""
        f = tmp_path / "s.py"
        f.write_text("# PLACEHOLDER\nx = 1\nimport os\n")
        rc = check_tool_event(
            "Edit",
            {
                "file_path": str(f),
                "old_string": "# PLACEHOLDER",
                "new_string": "# line a\n# line b",  # range becomes [1, 2]
                "replace_all": False,
            },
        )
        # import os is now at line 4, outside [1, 2]
        assert rc == 0

    def test_write_with_violation_is_blocked(self, tmp_path):
        rc = check_tool_event(
            "Write",
            {
                "file_path": str(tmp_path / "new.py"),
                "content": "import os\nx = 1\n",
            },
        )
        assert rc == 2

    def test_write_clean_file_is_allowed(self, tmp_path):
        rc = check_tool_event(
            "Write",
            {
                "file_path": str(tmp_path / "new.py"),
                "content": "x = 1\n",
            },
        )
        assert rc == 0

    def test_non_python_file_is_allowed(self, tmp_path):
        rc = check_tool_event(
            "Edit",
            {
                "file_path": str(tmp_path / "README.md"),
                "old_string": "old",
                "new_string": "import os",
                "replace_all": False,
            },
        )
        assert rc == 0

    def test_unknown_tool_is_allowed(self):
        rc = check_tool_event("Bash", {"command": "rm -rf /"})
        assert rc == 0
