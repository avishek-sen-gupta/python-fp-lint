# tests/test_reassignment_gate.py
"""Tests for the ReassignmentGate — beniget-based reassignment detection."""

import os

import beniget
import pytest

from python_fp_lint import lint_gate
from python_fp_lint.reassignment_gate import ReassignmentGate
from python_fp_lint.result import BackendError, LintResult


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
        assert type(result) is LintResult

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
        assert [v.rule for v in result.violations].count("reassignment") == 1

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
        assert (v.rule, os.path.basename(v.file), v.line) == (
            "reassignment",
            "dirty.py",
            3,
        )
        assert v.message == "'x' reassigned (scope: function foo())"

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


class TestAnalysisFailure:
    """A file beniget cannot analyse is an error, never a clean result: the
    ratchet would bank the missing reassignments as a fall."""

    @pytest.fixture
    def broken_beniget(self, monkeypatch):
        def explode(self, node):
            raise RuntimeError("chain construction failed")

        monkeypatch.setattr(beniget.DefUseChains, "visit", explode)

    def test_raises_backend_error_naming_the_file(self, tmp_path, broken_beniget):
        path = _make_file(str(tmp_path), "odd.py", "x = 1\nx = 2\n")
        with pytest.raises(BackendError, match=r"odd\.py.*chain construction failed"):
            ReassignmentGate().evaluate([path], str(tmp_path))

    def test_unparseable_file_is_still_left_to_ruff(self, tmp_path, broken_beniget):
        """A syntax error never reaches beniget; Ruff reports it instead."""
        path = _make_file(str(tmp_path), "broken.py", "def (:\n")
        result = ReassignmentGate().evaluate([path], str(tmp_path))
        assert result.violations == []

    def test_is_the_same_error_lint_gate_exports(self):
        assert lint_gate.BackendError is BackendError
