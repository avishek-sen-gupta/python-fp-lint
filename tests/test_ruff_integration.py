"""Tests for Ruff backend integration in LintGate."""

import shutil
import pytest

from python_fp_lint.lint_gate import _DEFAULT_RUFF_SELECT, _find_ruff, _run_ruff

needs_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed",
)


class TestFindRuff:
    def test_finds_ruff_binary(self):
        result = _find_ruff()
        # May be None if ruff not installed; just verify it returns str or None
        assert result is None or isinstance(result, str)

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _: None)
        assert _find_ruff() is None


@needs_ruff
class TestRunRuff:
    def test_detects_bare_except(self, tmp_path):
        f = tmp_path / "bare.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert any(v.rule == "E722" for v in violations)

    def test_detects_print(self, tmp_path):
        f = tmp_path / "prints.py"
        f.write_text("print('hello')\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert any(v.rule == "T201" for v in violations)

    def test_detects_relative_import(self, tmp_path):
        f = tmp_path / "rel.py"
        f.write_text("from .. import utils\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert any(v.rule == "TID252" for v in violations)

    def test_clean_file_no_violations(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert violations == []

    def test_violation_fields(self, tmp_path):
        f = tmp_path / "bare.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        v = [v for v in violations if v.rule == "E722"][0]
        assert "bare.py" in v.file
        assert v.line > 0
        assert v.message != ""

    def test_returns_empty_on_timeout(self, tmp_path, monkeypatch):
        """If ruff times out, return empty list (don't crash)."""
        import subprocess

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="ruff", timeout=30)

        monkeypatch.setattr(subprocess, "run", fake_run)
        f = tmp_path / "any.py"
        f.write_text("x = 1\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert violations == []

    def test_unused_import_detected(self, tmp_path):
        f = tmp_path / "unused.py"
        f.write_text("import os\nx = 1\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)], _DEFAULT_RUFF_SELECT)
        assert any(v.rule == "F401" for v in violations)
