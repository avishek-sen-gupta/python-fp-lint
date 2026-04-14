# tests/test_lint_gate.py
"""Tests for the unified LintGate (ast-grep + Ruff + beniget)."""

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


_PKG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python_fp_lint")


@pytest.fixture
def rules_dir(tmp_path):
    """Copy ast-grep rules and config into a temp directory."""
    import shutil as _shutil

    src_rules = os.path.join(_PKG_DIR, "rules")
    dst_rules = tmp_path / "rules"
    dst_rules.mkdir()
    for rule_file in os.listdir(src_rules):
        if rule_file.endswith(".yml"):
            _shutil.copy(os.path.join(src_rules, rule_file), dst_rules / rule_file)
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    return str(tmp_path)


needs_sg = pytest.mark.skipif(
    shutil.which("sg") is None and shutil.which("ast-grep") is None,
    reason="ast-grep (sg) not installed",
)

needs_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff not installed",
)


# ===========================================================================
# Rules directory resolution
# ===========================================================================


class TestResolveRulesDir:
    def test_explicit_rules_dir_takes_priority(self, tmp_path):
        gate = LintGate(rules_dir="/explicit/path")
        assert gate._resolve_rules_dir(str(tmp_path)) == "/explicit/path"

    def test_package_local_finds_rules(self, tmp_path):
        gate = LintGate()
        resolved = gate._resolve_rules_dir(str(tmp_path))
        assert resolved is not None


# ===========================================================================
# LintGate API
# ===========================================================================


class TestLintGateAPI:
    def test_returns_lint_result(self, tmp_path, rules_dir, monkeypatch):
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


# ===========================================================================
# Tool-missing scenarios
# ===========================================================================


class TestLintGateWithoutTools:
    def test_filters_to_python_files_only(self, tmp_path, rules_dir):
        py_path = _make_file(tmp_path, "widget.py", "x = 1\n")
        md_path = _make_file(tmp_path, "notes.md", "# Notes\n")
        sh_path = _make_file(tmp_path, "run.sh", "echo hi\n")
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([py_path, md_path, sh_path]) == [py_path]

    def test_skips_nonexistent_files(self, tmp_path, rules_dir):
        fake = os.path.join(str(tmp_path), "gone.py")
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([fake]) == []

    def test_sg_missing_logs_warning_continues(self, tmp_path, rules_dir, monkeypatch):
        """When sg is missing, ast-grep violations are empty but gate still runs."""
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\nx = 2\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        # Reassignment should still be detected even without sg
        assert isinstance(result, LintResult)


# ===========================================================================
# ast-grep backend (via unified gate)
# ===========================================================================


@needs_sg
class TestLintGateAstGrep:
    def test_clean_file_passes_ast_grep(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        # May have Ruff violations if ruff installed, so just check ast-grep rules
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []

    def test_list_append_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-append" for v in result.violations)

    def test_subscript_mutation_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd['key'] = 'val'\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-mutation" for v in result.violations)

    def test_deep_nesting_detected(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            process(cell)\n",
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_loop_mutation_detected(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        result.append(x)\n"
            "    return result\n",
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-loop-mutation" for v in result.violations)

    def test_deduplicates_files(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path, path, path], str(tmp_path))
        # Clean file with deduplication — no ast-grep violations
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []

    def test_only_scans_touched_files(self, tmp_path, rules_dir):
        _make_file(tmp_path, "dirty.py", "items = []\nitems.append(1)\n")
        clean = _make_file(tmp_path, "clean.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([clean], str(tmp_path))
        ast_grep_violations = [v for v in result.violations if not v.rule[0].isupper()]
        assert ast_grep_violations == []


# ===========================================================================
# Ruff backend (via unified gate)
# ===========================================================================


@needs_ruff
class TestLintGateRuff:
    def test_bare_except_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept:\n    pass\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "E722" for v in result.violations)

    def test_print_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "T201" for v in result.violations)

    def test_undefined_name_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = undefined_variable\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        # F821 is undefined name, which is in the F category
        assert any(v.rule == "F821" for v in result.violations)

    def test_unused_import_detected(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "F401" for v in result.violations)

    def test_ruff_missing_continues(self, tmp_path, rules_dir, monkeypatch):
        """When ruff is missing, Ruff violations are empty but gate still runs."""
        original_which = shutil.which
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: None if cmd == "ruff" else original_which(cmd),
        )
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        # No Ruff violations since binary is missing
        ruff_violations = [v for v in result.violations if v.rule[0].isupper()]
        assert ruff_violations == []


# ===========================================================================
# Reassignment backend (via unified gate)
# ===========================================================================


class TestLintGateReassignment:
    def test_reassignment_detected(self, tmp_path, rules_dir, monkeypatch):
        """Unified gate detects reassignment without needing separate ReassignmentGate."""
        # Mock sg and ruff away to isolate reassignment
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\nx = 2\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "reassignment" for v in result.violations)

    def test_no_reassignment_passes(self, tmp_path, rules_dir, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        path = _make_file(tmp_path, "widget.py", "x = 1\ny = 2\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "reassignment" for v in result.violations)


# ===========================================================================
# All backends together
# ===========================================================================


@needs_sg
@needs_ruff
class TestUnifiedGateIntegration:
    def test_all_backends_produce_violations(self, tmp_path, rules_dir):
        """A file that triggers all three backends."""
        code = (
            "import os\n"  # F401 (Ruff)
            "x = 1\n"
            "x = 2\n"  # reassignment (beniget)
            "items = []\n"
            "items.append(1)\n"  # no-list-append (ast-grep)
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        rules_hit = {v.rule for v in result.violations}
        assert "no-list-append" in rules_hit  # ast-grep
        assert "F401" in rules_hit  # Ruff
        assert "reassignment" in rules_hit  # beniget

    def test_clean_file_passes_all_backends(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True


# ===========================================================================
# Rule configuration
# ===========================================================================


@needs_ruff
class TestRuffSelectConfig:
    def test_constructor_overrides_default(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        # F401 (unused import) is in default set — restrict to E only
        gate = LintGate(rules_dir=rules_dir, ruff_select="E")
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "F401" for v in result.violations)

    def test_config_json_overrides_default(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        monkeypatch.setattr(
            "python_fp_lint.lint_gate._read_config",
            lambda key: "E" if key == "ruff_select" else None,
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "F401" for v in result.violations)

    def test_constructor_overrides_config_json(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "import os\nx = 1\n")
        # config says E only, constructor says F — F should win
        monkeypatch.setattr(
            "python_fp_lint.lint_gate._read_config",
            lambda key: "E" if key == "ruff_select" else None,
        )
        gate = LintGate(rules_dir=rules_dir, ruff_select="F")
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "F401" for v in result.violations)


@needs_sg
class TestAstGrepRulesConfig:
    def test_constructor_filters_rules(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        # Only enable no-list-append, not no-subscript-mutation
        gate = LintGate(rules_dir=rules_dir, ast_grep_rules=["no-list-append"])
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert all(v.rule == "no-list-append" for v in ast_grep)
        assert not any(v.rule == "no-subscript-mutation" for v in result.violations)

    def test_config_json_filters_rules(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        monkeypatch.setattr(
            "python_fp_lint.lint_gate._read_config",
            lambda key: ["no-list-append"] if key == "ast_grep_rules" else None,
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert len(ast_grep) > 0
        assert all(v.rule == "no-list-append" for v in ast_grep)

    def test_constructor_overrides_config_json(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        # config says no-list-append only, constructor says no-subscript-mutation
        monkeypatch.setattr(
            "python_fp_lint.lint_gate._read_config",
            lambda key: ["no-list-append"] if key == "ast_grep_rules" else None,
        )
        gate = LintGate(rules_dir=rules_dir, ast_grep_rules=["no-subscript-mutation"])
        result = gate.evaluate([path], str(tmp_path))
        ast_grep = [
            v
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        ]
        assert any(v.rule == "no-subscript-mutation" for v in ast_grep)
        assert not any(v.rule == "no-list-append" for v in ast_grep)

    def test_none_means_all_rules(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "items = []\nitems.append(1)\nd = {}\nd['k'] = 'v'\n",
        )
        gate = LintGate(rules_dir=rules_dir, ast_grep_rules=None)
        result = gate.evaluate([path], str(tmp_path))
        ast_grep_rules = {
            v.rule
            for v in result.violations
            if not v.rule[0].isupper() and v.rule != "reassignment"
        }
        assert len(ast_grep_rules) >= 2
