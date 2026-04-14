# tests/test_lint_gate.py
"""Tests for LintGate — dual-backend lint checking."""

import os
import shutil
import pytest

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.result import LintResult


def _make_file(tmp_path, filename, content):
    """Write a Python file and return its path."""
    path = os.path.join(tmp_path, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture
def rules_dir(tmp_path):
    """Create a minimal rules directory with one Semgrep rule."""
    semgrep_rules = tmp_path / "semgrep-rules.yml"
    semgrep_rules.write_text(
        "rules:\n"
        "  - id: no-bare-except\n"
        "    pattern: |\n"
        "      try:\n"
        "          ...\n"
        "      except:\n"
        "          ...\n"
        '    message: "Bare except"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
    )
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    rules = tmp_path / "rules"
    rules.mkdir()
    return str(tmp_path)


needs_semgrep = pytest.mark.skipif(
    shutil.which("semgrep") is None,
    reason="semgrep not installed",
)

needs_sg = pytest.mark.skipif(
    shutil.which("sg") is None and shutil.which("ast-grep") is None,
    reason="ast-grep (sg) not installed",
)


class TestLintGateAPI:
    """Verify the new standalone API returns LintResult."""

    def test_returns_lint_result(self, tmp_path, rules_dir, monkeypatch):
        """evaluate() returns a LintResult, not a GateResult."""
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert isinstance(result, LintResult)

    def test_no_python_files_passes(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "README.md", "# Hello")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True
        assert result.violations == []

    def test_empty_files_passes(self, tmp_path, rules_dir):
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([], str(tmp_path))
        assert result.passed is True

    def test_fails_when_semgrep_missing(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any("semgrep" in v.message.lower() for v in result.violations)


@needs_semgrep
class TestLintGateWithSemgrep:
    """Tests that require Semgrep installed."""

    def test_clean_file_passes(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_bare_except_fails(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "try:\n    x = 1\nexcept:\n    pass\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-bare-except" for v in result.violations)

    def test_violations_have_correct_fields(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "try:\n    x = 1\nexcept:\n    pass\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        v = result.violations[0]
        assert v.rule == "no-bare-except"
        assert "widget.py" in v.file
        assert v.line > 0
        assert v.message != ""

    def test_deduplicates_files(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path, path, path], str(tmp_path))
        assert result.passed is True
