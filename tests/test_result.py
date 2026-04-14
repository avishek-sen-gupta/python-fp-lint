# tests/test_result.py
"""Tests for LintResult and LintViolation types."""

from python_fp_lint.result import LintResult, LintViolation


class TestLintViolation:
    def test_fields(self):
        v = LintViolation(rule="no-print", file="app.py", line=10, message="print() found")
        assert v.rule == "no-print"
        assert v.file == "app.py"
        assert v.line == 10
        assert v.message == "print() found"


class TestLintResult:
    def test_passing_result(self):
        r = LintResult(passed=True, violations=[])
        assert r.passed is True
        assert r.violations == []

    def test_failing_result(self):
        v = LintViolation(rule="no-print", file="app.py", line=10, message="print() found")
        r = LintResult(passed=False, violations=[v])
        assert r.passed is False
        assert len(r.violations) == 1
        assert r.violations[0].rule == "no-print"
