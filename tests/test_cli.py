# tests/test_cli.py
"""CLI integration tests for python -m python_fp_lint check."""

import os
import subprocess

import pytest


@pytest.fixture
def clean_file(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n")
    return str(f)


@pytest.fixture
def dirty_file(tmp_path):
    f = tmp_path / "dirty.py"
    f.write_text('d = {}\nd["key"] = "value"\n')
    return str(f)


def _run_check(*args):
    return subprocess.run(
        ["python3", "-m", "python_fp_lint", "check", *args],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )


def _run_bare(*args):
    """Run without the 'check' subcommand."""
    return subprocess.run(
        ["python3", "-m", "python_fp_lint", *args],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )


class TestCLI:
    def test_clean_file_exits_zero(self, clean_file):
        result = _run_check(clean_file)
        assert result.returncode == 0
        assert "No violations" in result.stdout

    def test_dirty_file_exits_nonzero(self, dirty_file):
        result = _run_check(dirty_file)
        assert result.returncode == 1
        assert "violation" in result.stdout

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text('d = {}\nd["k"] = 1\n')
        (tmp_path / "b.py").write_text("x = 1\n")
        result = _run_check(str(tmp_path / "a.py"), str(tmp_path / "b.py"))
        assert result.returncode == 1
        assert "no-subscript-mutation" in result.stdout

    def test_no_subcommand_exits_with_help(self):
        result = _run_bare()
        assert result.returncode == 1

    def test_setitem_detected(self, tmp_path):
        f = tmp_path / "setitem.py"
        f.write_text('d = {}\nd.__setitem__("k", 1)\n')
        result = _run_check(str(f))
        assert result.returncode == 1
        assert "no-setitem-call" in result.stdout

    def test_semgrep_only_flag(self, tmp_path):
        f = tmp_path / "reassign.py"
        f.write_text("x = 1\nx = 2\n")
        result = _run_check("--semgrep-only", str(f))
        # Reassignment not checked with --semgrep-only
        assert result.returncode == 0

    def test_reassignment_only_flag(self, tmp_path):
        f = tmp_path / "reassign.py"
        f.write_text("x = 1\nx = 2\n")
        result = _run_check("--reassignment-only", str(f))
        assert result.returncode == 1
        assert "violation" in result.stdout
