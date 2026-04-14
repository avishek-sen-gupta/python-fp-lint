# tests/test_lint_gate.py
"""Tests for LintGate (pure ast-grep) and MixedLintGate (Semgrep + ast-grep)."""

import os
import shutil
import pytest

from python_fp_lint.lint_gate import LintGate, MixedLintGate
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
    """Copy the real Semgrep rules, ast-grep rules, and config into a temp directory."""
    import shutil as _shutil

    _shutil.copy(
        os.path.join(_PKG_DIR, "semgrep-rules.yml"), tmp_path / "semgrep-rules.yml"
    )
    src_rules = os.path.join(_PKG_DIR, "rules")
    dst_rules = tmp_path / "rules"
    dst_rules.mkdir()
    for rule_file in os.listdir(src_rules):
        if rule_file.endswith(".yml"):
            _shutil.copy(os.path.join(src_rules, rule_file), dst_rules / rule_file)
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    return str(tmp_path)


needs_semgrep = pytest.mark.skipif(
    shutil.which("semgrep") is None,
    reason="semgrep not installed",
)

needs_sg = pytest.mark.skipif(
    shutil.which("sg") is None and shutil.which("ast-grep") is None,
    reason="ast-grep (sg) not installed",
)


# ===========================================================================
# LintGate — pure ast-grep backend
# ===========================================================================


class TestResolveRulesDir:
    """Tests for rules directory resolution logic."""

    def test_explicit_rules_dir_takes_priority(self, tmp_path):
        gate = LintGate(rules_dir="/explicit/path")
        assert gate._resolve_rules_dir(str(tmp_path)) == "/explicit/path"

    def test_package_local_finds_rules(self, tmp_path):
        gate = LintGate()
        resolved = gate._resolve_rules_dir(str(tmp_path))
        assert resolved is not None


class TestLintGateAPI:
    """Verify the LintGate API returns LintResult."""

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

    def test_fails_when_sg_missing(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any("ast-grep" in v.message.lower() for v in result.violations)


class TestLintGateWithoutTools:
    """Tests that work without linting tools installed."""

    def test_filters_to_python_files_only(self, tmp_path, rules_dir):
        py_path = _make_file(tmp_path, "widget.py", "x = 1\n")
        md_path = _make_file(tmp_path, "notes.md", "# Notes\n")
        sh_path = _make_file(tmp_path, "run.sh", "echo hi\n")
        gate = LintGate(rules_dir=rules_dir)
        filtered = gate.evaluate.__func__  # just test the helper
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([py_path, md_path, sh_path]) == [py_path]

    def test_skips_nonexistent_files(self, tmp_path, rules_dir):
        fake = os.path.join(str(tmp_path), "gone.py")
        from python_fp_lint.lint_gate import _filter_python_files

        assert _filter_python_files([fake]) == []


@needs_sg
class TestLintGateWithSg:
    """Tests for LintGate (pure ast-grep)."""

    def test_clean_file_passes(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_except_exception_fails(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path, "widget.py", "try:\n    x = 1\nexcept Exception:\n    pass\n"
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-except-exception" for v in result.violations)

    def test_violations_have_correct_fields(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path, "widget.py", "try:\n    x = 1\nexcept Exception:\n    pass\n"
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        v = result.violations[0]
        assert v.rule == "no-except-exception"
        assert "widget.py" in v.file
        assert v.line > 0
        assert v.message != ""

    def test_deduplicates_files(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path, path, path], str(tmp_path))
        assert result.passed is True

    def test_multiple_violations_reported(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path, "widget.py", "items = []\nitems.append(1)\nitems.pop(0)\n"
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert len(result.violations) >= 2

    def test_only_scans_touched_files(self, tmp_path, rules_dir):
        dirty = _make_file(
            tmp_path, "dirty.py", "try:\n    x = 1\nexcept Exception:\n    pass\n"
        )
        clean = _make_file(tmp_path, "clean.py", "x = 1\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([clean], str(tmp_path))
        assert result.passed is True

    def test_list_append_fails(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-append" for v in result.violations)

    def test_subscript_mutation_fails(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd['key'] = 'val'\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-mutation" for v in result.violations)

    def test_deep_nesting_fails(self, tmp_path, rules_dir):
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

    def test_loop_mutation_fails(self, tmp_path, rules_dir):
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

    def test_optional_none_fails(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "from typing import Optional\ndef f(x: Optional[str]):\n    pass\n",
        )
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)


# ===========================================================================
# MixedLintGate — Semgrep + ast-grep backend
# ===========================================================================


# Comprehensive fixture file that triggers every Semgrep rule exactly once.
# Each section is labelled so test failures point to the relevant rule.
_SEMGREP_FIXTURE = """\
from typing import Optional, Union

# --- list mutation ---
items = []
items.append(1)          # no-list-append
items.extend([2])        # no-list-extend
items.insert(0, 0)       # no-list-insert
items.pop(0)             # no-list-pop
items.remove(1)          # no-list-remove

# --- dict mutation ---
d = {}
d.clear()                # no-dict-clear
d.update({"a": 1})       # no-dict-update
d.setdefault("k", [])    # no-dict-setdefault

# --- set mutation ---
s = set()
s.add(1)                 # no-set-add
s.discard(1)             # no-set-discard

# --- subscript mutation ---
d["key"] = "val"         # no-subscript-mutation
del d["key"]             # no-subscript-del
d["a"] += 1              # no-subscript-augmented-mutation
d["a"], d["b"] = 1, 2   # no-subscript-tuple-mutation
d.__setitem__("k", "v")  # no-setitem-call

# --- augmented assignment ---
class _C:
    x = 0
_c = _C()
_c.x += 1               # no-attribute-augmented-mutation
_y = 1
_y += 1                  # no-local-augmented-mutation

# --- None / Optional ---
if _y is None:           # no-is-none
    pass
if _y is not None:       # no-is-not-none
    pass

def _fn_none(x=None):    # no-none-default-param
    return x

def _fn_opt(x: Optional[str]):     # no-optional-none (Optional)
    pass

def _fn_pipe(x: str | None):       # no-optional-none (pipe)
    pass

def _fn_union(x: Union[str, None]):  # no-optional-none (Union)
    pass

# --- exceptions ---
try:
    _z = 1
except Exception:        # no-except-exception
    pass

# --- style ---
class _D:
    @staticmethod        # no-static-method
    def bar():
        pass
"""

# All 23 Semgrep rule IDs — every one must fire on the fixture above.
_ALL_SEMGREP_RULES = [
    "no-list-append",
    "no-list-extend",
    "no-list-insert",
    "no-list-pop",
    "no-list-remove",
    "no-dict-clear",
    "no-dict-update",
    "no-dict-setdefault",
    "no-set-add",
    "no-set-discard",
    "no-subscript-mutation",
    "no-subscript-del",
    "no-subscript-augmented-mutation",
    "no-subscript-tuple-mutation",
    "no-setitem-call",
    "no-attribute-augmented-mutation",
    "no-local-augmented-mutation",
    "no-is-none",
    "no-is-not-none",
    "no-none-default-param",
    "no-optional-none",
    "no-except-exception",
    "no-static-method",
]


@pytest.fixture(scope="module")
def semgrep_violations(tmp_path_factory):
    """Run Semgrep once on the comprehensive fixture, return cached violations."""
    if shutil.which("semgrep") is None:
        pytest.skip("semgrep not installed")
    tmp = tmp_path_factory.mktemp("semgrep")
    path = str(tmp / "fixture.py")
    with open(path, "w") as f:
        f.write(_SEMGREP_FIXTURE)
    rules_file = os.path.join(_PKG_DIR, "semgrep-rules.yml")
    from python_fp_lint.lint_gate import _run_semgrep

    return _run_semgrep(shutil.which("semgrep"), rules_file, [path])


class TestSemgrepRuleCoverage:
    """Every Semgrep rule fires on the comprehensive fixture (single invocation)."""

    @pytest.mark.parametrize("rule_id", _ALL_SEMGREP_RULES)
    def test_rule_fires(self, semgrep_violations, rule_id):
        matched = [v for v in semgrep_violations if v.rule == rule_id]
        assert matched, f"rule {rule_id} did not fire on the fixture"


# --- Negative tests: one Semgrep invocation for clean code ---

_CLEAN_FIXTURE = """\
import os
import logging
from collections import defaultdict

def compute(x: int, y: int) -> int:
    return x + y

def greet(name: str) -> str:
    return f"hello {name}"

items = [1] + [2, 3]
d = {**{"a": 1}, **{"b": 2}}
s = {1} | {2}
a, b = 1, 2

try:
    x = 1
except ValueError:
    pass

class Foo:
    @classmethod
    def bar(cls):
        pass
"""


@pytest.fixture(scope="module")
def clean_semgrep_violations(tmp_path_factory):
    """Run Semgrep once on clean code — should produce zero violations."""
    if shutil.which("semgrep") is None:
        pytest.skip("semgrep not installed")
    tmp = tmp_path_factory.mktemp("semgrep_clean")
    path = str(tmp / "clean.py")
    with open(path, "w") as f:
        f.write(_CLEAN_FIXTURE)
    rules_file = os.path.join(_PKG_DIR, "semgrep-rules.yml")
    from python_fp_lint.lint_gate import _run_semgrep

    return _run_semgrep(shutil.which("semgrep"), rules_file, [path])


class TestSemgrepCleanCode:
    """Clean code should not trigger any Semgrep rules."""

    def test_no_violations(self, clean_semgrep_violations):
        assert clean_semgrep_violations == []


# --- MixedLintGate integration tests (gate behaviour, not per-rule coverage) ---


@needs_semgrep
class TestMixedLintGateIntegration:
    """Tests for MixedLintGate integration behaviour."""

    def test_clean_file_passes(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_fails_when_semgrep_missing(self, tmp_path, rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        monkeypatch.setattr(shutil, "which", lambda _: None)
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any("semgrep" in v.message.lower() for v in result.violations)

    @needs_sg
    def test_deep_nesting_via_ast_grep(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            process(cell)\n",
        )
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    @needs_sg
    def test_loop_mutation_via_ast_grep(self, tmp_path, rules_dir):
        path = _make_file(
            tmp_path,
            "widget.py",
            "def f(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        result.append(x)\n"
            "    return result\n",
        )
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-loop-mutation" for v in result.violations)

    @needs_sg
    def test_both_backends_violations_merged(self, tmp_path, rules_dir):
        code = (
            "def f(matrix):\n"
            "    result = []\n"
            "    result.append(1)\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            pass\n"
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        rule_ids = [v.rule for v in result.violations]
        assert any("no-list-append" in r for r in rule_ids)
        assert any("no-deep-nesting" in r for r in rule_ids)

    @needs_sg
    def test_sg_only_rules_filtered(self, tmp_path, rules_dir):
        """MixedLintGate should not duplicate rules that Semgrep already covers."""
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        rule_ids = [v.rule for v in result.violations]
        assert rule_ids.count("no-list-append") == 1

    def test_ast_grep_missing_semgrep_still_works(
        self, tmp_path, rules_dir, monkeypatch
    ):
        original_which = shutil.which
        monkeypatch.setattr(
            shutil,
            "which",
            lambda cmd: None if cmd in ("sg", "ast-grep") else original_which(cmd),
        )
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = MixedLintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-list-append" for v in result.violations)
