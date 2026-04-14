# tests/test_reassignment_gate.py
"""Tests for the ReassignmentGate — beniget-based reassignment detection."""

import os
import pytest

from python_fp_lint.reassignment_gate import ReassignmentGate
from python_fp_lint.result import LintResult


def _make_file(tmp_path, filename, content):
    """Write a Python file and return its path."""
    path = os.path.join(tmp_path, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


class TestReassignmentGateCleanCode:
    """Code that should PASS — no reassignment."""

    def test_returns_lint_result(self, tmp_path):
        path = _make_file(str(tmp_path), "clean.py", "x = 1\n")
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert isinstance(result, LintResult)

    def test_single_assignment_passes(self, tmp_path):
        path = _make_file(str(tmp_path), "clean.py", "x = 1\ny = 2\n")
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_assignments_in_separate_scopes_pass(self, tmp_path):
        code = (
            "def foo():\n"
            "    x = 1\n"
            "    return x\n"
            "\n"
            "def bar():\n"
            "    x = 2\n"
            "    return x\n"
        )
        path = _make_file(str(tmp_path), "clean.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_no_python_files_passes(self, tmp_path):
        path = _make_file(str(tmp_path), "readme.md", "# Hello\n")
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_empty_file_passes(self, tmp_path):
        path = _make_file(str(tmp_path), "empty.py", "")
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_function_params_not_flagged_as_dups(self, tmp_path):
        code = "def foo(x, y):\n    return x + y\n"
        path = _make_file(str(tmp_path), "clean.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_for_loop_target_not_flagged(self, tmp_path):
        code = "result = [i * 2 for i in range(10)]\n"
        path = _make_file(str(tmp_path), "clean.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_unpacking_not_flagged(self, tmp_path):
        code = "a, b, c = 1, 2, 3\n"
        path = _make_file(str(tmp_path), "clean.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True


class TestReassignmentGateDetection:
    """Code that should FAIL — contains reassignment."""

    def test_variable_reassignment_in_function(self, tmp_path):
        code = "def foo():\n" "    x = 1\n" "    x = 2\n" "    return x\n"
        path = _make_file(str(tmp_path), "dirty.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "reassignment" for v in result.violations)

    def test_parameter_reassignment(self, tmp_path):
        code = "def foo(x):\n" "    x = x + 1\n" "    return x\n"
        path = _make_file(str(tmp_path), "dirty.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_module_level_reassignment(self, tmp_path):
        code = "x = 1\nx = 2\n"
        path = _make_file(str(tmp_path), "dirty.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_multiple_reassignments_reported(self, tmp_path):
        code = (
            "def foo():\n"
            "    a = 1\n"
            "    b = 2\n"
            "    a = 3\n"
            "    b = 4\n"
            "    return a + b\n"
        )
        path = _make_file(str(tmp_path), "dirty.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert len(result.violations) >= 2

    def test_violation_has_correct_fields(self, tmp_path):
        code = "def foo():\n    x = 1\n    x = 2\n    return x\n"
        path = _make_file(str(tmp_path), "dirty.py", code)
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        v = result.violations[0]
        assert v.rule == "reassignment"
        assert "dirty.py" in v.file
        assert v.line > 0
        assert "x" in v.message

    def test_only_scans_provided_files(self, tmp_path):
        _make_file(str(tmp_path), "dirty.py", "x = 1\nx = 2\n")
        clean = _make_file(str(tmp_path), "clean.py", "y = 1\n")
        gate = ReassignmentGate()
        result = gate.evaluate([clean], str(tmp_path))
        assert result.passed is True

    def test_syntax_error_file_passes(self, tmp_path):
        path = _make_file(str(tmp_path), "broken.py", "def foo(\n")
        gate = ReassignmentGate()
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_nonexistent_file_passes(self, tmp_path):
        gate = ReassignmentGate()
        result = gate.evaluate(["/nonexistent/file.py"], str(tmp_path))
        assert result.passed is True
