# tests/test_cli.py
"""CLI integration tests for python -m python_fp_lint."""

import json
import os
import subprocess
import sys

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
        [sys.executable, "-m", "python_fp_lint", "check", *args],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )


def _run_bare(*args):
    """Run without the 'check' subcommand."""
    return subprocess.run(
        [sys.executable, "-m", "python_fp_lint", *args],
        capture_output=True,
        text=True,
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


class TestJSONOutput:
    def test_clean_file_json(self, clean_file):
        result = _run_bare("--format", "json", "check", clean_file)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["passed"] is True
        assert data["violation_count"] == 0
        assert data["violations"] == []

    def test_dirty_file_json(self, dirty_file):
        result = _run_bare("--format", "json", "check", dirty_file)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["violation_count"] > 0
        v = data["violations"][0]
        assert set(v.keys()) == {"rule", "file", "line", "message"}
        assert isinstance(v["line"], int)

    def test_json_output_is_valid_json(self, dirty_file):
        result = _run_bare("--format", "json", "check", dirty_file)
        json.loads(result.stdout)  # must not raise


class TestDirectoryAndGlob:
    def test_directory_recursive(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "a.py").write_text("x = []\nx.append(1)\n")
        result = _run_bare("--format", "json", "check", str(tmp_path))
        data = json.loads(result.stdout)
        assert data["violation_count"] >= 1
        assert any(v["rule"] == "no-list-append" for v in data["violations"])

    def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("x = []\nx.append(1)\n")
        (tmp_path / "b.txt").write_text("x = []\nx.append(1)\n")
        # Quoted glob — bypasses shell expansion, handled by _expand_paths
        result = _run_bare("--format", "json", "check", str(tmp_path / "*.py"))
        data = json.loads(result.stdout)
        assert data["violation_count"] >= 1
        assert all(v["file"].endswith(".py") for v in data["violations"])

    def test_mix_files_and_dirs(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "mod.py").write_text("x = []\nx.append(1)\n")
        f = tmp_path / "standalone.py"
        f.write_text('d = {}\nd["k"] = 1\n')
        result = _run_bare("--format", "json", "check", str(d), str(f))
        data = json.loads(result.stdout)
        files = {v["file"] for v in data["violations"]}
        assert len(files) == 2


class TestRulesCommand:
    def test_rules_text(self):
        result = _run_bare("rules")
        assert result.returncode == 0
        assert "ast-grep" in result.stdout
        assert "semgrep" in result.stdout
        assert "beniget" in result.stdout

    def test_rules_json(self):
        result = _run_bare("--format", "json", "rules")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0
        backends = {r["backend"] for r in data}
        assert backends == {"ast-grep", "semgrep", "beniget"}
        for r in data:
            assert set(r.keys()) == {"id", "message", "severity", "backend"}

    def test_rules_includes_known_rules(self):
        result = _run_bare("--format", "json", "rules")
        data = json.loads(result.stdout)
        ids = {r["id"] for r in data}
        assert "no-list-append" in ids
        assert "no-deep-nesting" in ids
        assert "reassignment" in ids


class TestSchemaCommand:
    def test_schema_is_valid_json(self):
        result = _run_bare("schema")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "check_output" in data
        assert "rules_output" in data

    def test_schema_describes_violations(self):
        result = _run_bare("schema")
        data = json.loads(result.stdout)
        props = data["check_output"]["properties"]
        assert "passed" in props
        assert "violations" in props
        assert "violation_count" in props


class TestSelfLint:
    """Run the linter on this repo's own source code."""

    def test_lintgate_finds_violations_in_own_codebase(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        result = _run_bare(
            "--format", "json", "check", os.path.join(repo_root, "python_fp_lint")
        )
        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["violation_count"] > 0
        rules_hit = {v["rule"] for v in data["violations"]}
        # The linter's own code uses patterns it flags
        assert len(rules_hit) > 1, f"Expected multiple rule types, got: {rules_hit}"
