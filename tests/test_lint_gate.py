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


@pytest.fixture
def multi_rules_dir(tmp_path):
    """Create a rules directory with multiple Semgrep rules."""
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
        "  - id: no-print\n"
        "    pattern: print(...)\n"
        '    message: "print() — use logging"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
    )
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    rules = tmp_path / "rules"
    rules.mkdir()
    return str(tmp_path)


@pytest.fixture
def mutation_rules_dir(tmp_path):
    """Create a rules directory with subscript mutation Semgrep rules."""
    semgrep_rules = tmp_path / "semgrep-rules.yml"
    semgrep_rules.write_text(
        "rules:\n"
        "  - id: no-subscript-mutation\n"
        "    pattern: $OBJ[$KEY] = $VAL\n"
        '    message: "Subscript mutation"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
        "  - id: no-subscript-augmented-mutation\n"
        "    patterns:\n"
        "      - pattern-either:\n"
        "          - pattern: $OBJ[$KEY] += $VAL\n"
        "          - pattern: $OBJ[$KEY] -= $VAL\n"
        "          - pattern: $OBJ[$KEY] *= $VAL\n"
        '    message: "Subscript augmented mutation"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
        "  - id: no-subscript-del\n"
        "    pattern: del $OBJ[$KEY]\n"
        '    message: "Subscript deletion"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
        "  - id: no-subscript-tuple-mutation\n"
        "    patterns:\n"
        "      - pattern-either:\n"
        "          - pattern: $OBJ[$KEY], ... = ...\n"
        "          - pattern: ..., $OBJ[$KEY] = ...\n"
        '    message: "Tuple subscript mutation"\n'
        "    severity: WARNING\n"
        "    languages: [python]\n"
    )
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    rules = tmp_path / "rules"
    rules.mkdir()
    return str(tmp_path)


@pytest.fixture
def nesting_rules_dir(tmp_path):
    """Create a rules directory with the no-deep-nesting rule."""
    rules = tmp_path / "rules"
    rules.mkdir()
    import shutil as _shutil
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "python_fp_lint", "rules", "no-deep-nesting.yml")
    _shutil.copy(src, rules / "no-deep-nesting.yml")
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    return str(tmp_path)


@pytest.fixture
def loop_mutation_rules_dir(tmp_path):
    """Create a rules directory with the no-loop-mutation rule."""
    rules = tmp_path / "rules"
    rules.mkdir()
    import shutil as _shutil
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "python_fp_lint", "rules", "no-loop-mutation.yml")
    _shutil.copy(src, rules / "no-loop-mutation.yml")
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    return str(tmp_path)


@pytest.fixture
def full_semgrep_rules(tmp_path):
    """Create a rules directory pointing to the real semgrep-rules.yml."""
    import shutil as _shutil
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "python_fp_lint", "semgrep-rules.yml")
    _shutil.copy(src, tmp_path / "semgrep-rules.yml")
    sgconfig = tmp_path / "sgconfig.yml"
    sgconfig.write_text("ruleDirs:\n  - rules\n")
    rules = tmp_path / "rules"
    rules.mkdir()
    return str(tmp_path)


@pytest.fixture
def dual_backend_rules_dir(tmp_path):
    """Create a rules directory with both Semgrep and ast-grep rules."""
    import shutil as _shutil
    src_semgrep = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "python_fp_lint", "semgrep-rules.yml")
    _shutil.copy(src_semgrep, tmp_path / "semgrep-rules.yml")
    rules = tmp_path / "rules"
    rules.mkdir()
    for rule in ["no-deep-nesting.yml", "no-loop-mutation.yml"]:
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "python_fp_lint", "rules", rule)
        _shutil.copy(src, rules / rule)
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


class TestResolveRulesDir:
    """Tests for rules directory resolution logic."""

    def test_explicit_rules_dir_takes_priority(self, tmp_path):
        gate = LintGate(rules_dir="/explicit/path")
        assert gate._resolve_rules_dir(str(tmp_path)) == "/explicit/path"

    def test_package_local_finds_rules(self, tmp_path):
        """When no explicit rules_dir is given, package-local rules are found."""
        gate = LintGate()
        # Call with tmp_path as project_root; should still find package-local
        resolved = gate._resolve_rules_dir(str(tmp_path))
        # Package-local (os.path.dirname(__file__)) should always win
        assert resolved is not None


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


class TestLintGateWithoutTools:
    """Tests that work without linting tools installed."""

    def test_filters_to_python_files_only(self, tmp_path, rules_dir):
        py_path = _make_file(tmp_path, "widget.py", "x = 1\n")
        md_path = _make_file(tmp_path, "notes.md", "# Notes\n")
        sh_path = _make_file(tmp_path, "run.sh", "echo hi\n")
        gate = LintGate(rules_dir=rules_dir)
        filtered = gate._filter_python_files([py_path, md_path, sh_path])
        assert filtered == [py_path]

    def test_skips_nonexistent_files(self, tmp_path, rules_dir):
        fake = os.path.join(str(tmp_path), "gone.py")
        gate = LintGate(rules_dir=rules_dir)
        filtered = gate._filter_python_files([fake])
        assert filtered == []


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

    def test_multiple_violations_reported(self, tmp_path, multi_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "try:\n    print('hi')\nexcept:\n    pass\n")
        gate = LintGate(rules_dir=multi_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert len(result.violations) >= 2

    def test_only_scans_touched_files(self, tmp_path, rules_dir):
        """Untouched files with violations should not cause failure."""
        dirty = _make_file(tmp_path, "dirty.py",
            "try:\n    x = 1\nexcept:\n    pass\n")
        clean = _make_file(tmp_path, "clean.py", "x = 1\n")
        # Only clean.py is in the files list
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([clean], str(tmp_path))
        assert result.passed is True

    def test_augmented_subscript_mutation_fails(self, tmp_path, mutation_rules_dir):
        """d[key] += amount should be caught."""
        path = _make_file(tmp_path, "widget.py",
            "def increment(d, key, amount=1):\n    d[key] += amount\n")
        gate = LintGate(rules_dir=mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-subscript-augmented-mutation" for v in result.violations)

    def test_subscript_del_fails(self, tmp_path, mutation_rules_dir):
        """del d[k] should be caught."""
        path = _make_file(tmp_path, "widget.py",
            "def remove(d, k):\n    del d[k]\n")
        gate = LintGate(rules_dir=mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-subscript-del" for v in result.violations)

    def test_tuple_subscript_mutation_fails(self, tmp_path, mutation_rules_dir):
        """d[k1], d[k2] = d[k2], d[k1] should be caught."""
        path = _make_file(tmp_path, "widget.py",
            "def swap(d, k1, k2):\n    d[k1], d[k2] = d[k2], d[k1]\n")
        gate = LintGate(rules_dir=mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-subscript-tuple-mutation" for v in result.violations)

    def test_all_dict_mutations_caught(self, tmp_path, mutation_rules_dir):
        """The exact code from test_dict.py should trigger violations."""
        code = (
            "def swap_values(d, key1, key2):\n"
            "    d[key1], d[key2] = d[key2], d[key1]\n"
            "\n"
            "def increment_value(d, key, amount=1):\n"
            "    d[key] += amount\n"
            "\n"
            "def filter_keys(d, keys):\n"
            "    for k in list(d):\n"
            "        if k not in keys:\n"
            "            del d[k]\n"
        )
        path = _make_file(tmp_path, "dict_transform.py", code)
        gate = LintGate(rules_dir=mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert len(result.violations) >= 3


@needs_sg
class TestDeepNestingRule:
    """Tests for the no-deep-nesting ast-grep rule."""

    def test_for_in_for_fails(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            process(cell)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_if_in_for_fails(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    for x in items:\n"
            "        if x > 0:\n"
            "            process(x)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_for_in_if_fails(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items, flag):\n"
            "    if flag:\n"
            "        for x in items:\n"
            "            process(x)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_if_in_if_fails(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(x, y):\n"
            "    if x > 0:\n"
            "        if y > 0:\n"
            "            process(x, y)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_triple_nesting_fails(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(cube):\n"
            "    for plane in cube:\n"
            "        for row in plane:\n"
            "            for cell in row:\n"
            "                process(cell)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_flat_for_passes(self, tmp_path, nesting_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    for x in items:\n"
            "        process(x)\n")
        gate = LintGate(rules_dir=nesting_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True


@needs_semgrep
class TestSemgrepMultilineAndComboRules:
    """Tests for multiline patterns and pattern-either Semgrep rules."""

    # --- no-bare-except ---
    def test_no_bare_except_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept:\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-bare-except" for v in result.violations)

    def test_no_bare_except_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept ValueError:\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-bare-except" for v in result.violations)

    # --- no-except-exception ---
    def test_no_except_exception_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept Exception:\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-except-exception" for v in result.violations)

    def test_no_except_exception_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "try:\n    x = 1\nexcept ValueError:\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-except-exception" for v in result.violations)

    # --- no-relative-import ---
    def test_no_relative_import_dot_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from . import utils\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-relative-import" for v in result.violations)

    def test_no_relative_import_dotdot_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from ..models import User\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-relative-import" for v in result.violations)

    def test_no_relative_import_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from mypackage import utils\nimport os\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-relative-import" for v in result.violations)

    # --- no-setitem-call ---
    def test_no_setitem_call_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd.__setitem__('k', 'v')\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-setitem-call" for v in result.violations)

    def test_no_setitem_call_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {'k': 'v'}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-setitem-call" for v in result.violations)

    # --- no-subscript-augmented-mutation ---
    def test_no_subscript_augmented_mutation_plus_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {'a': 1}\nd['a'] += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-augmented-mutation" for v in result.violations)

    def test_no_subscript_augmented_mutation_shift_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {'a': 8}\nd['a'] >>= 2\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-augmented-mutation" for v in result.violations)

    def test_no_subscript_augmented_mutation_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "x = 1\nx += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-subscript-augmented-mutation" for v in result.violations)

    # --- no-subscript-tuple-mutation ---
    def test_no_subscript_tuple_mutation_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd['a'], d['b'] = 1, 2\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-tuple-mutation" for v in result.violations)

    def test_no_subscript_tuple_mutation_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "a, b = 1, 2\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-subscript-tuple-mutation" for v in result.violations)

    # --- no-attribute-augmented-mutation ---
    def test_no_attribute_augmented_mutation_plus_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "class C:\n    x = 0\nc = C()\nc.x += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-attribute-augmented-mutation" for v in result.violations)

    def test_no_attribute_augmented_mutation_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "x = 1\nx += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-attribute-augmented-mutation" for v in result.violations)


@needs_semgrep
class TestSemgrepComplexRules:
    """Tests for rules using pattern-not, pattern-inside, and the new no-optional-none rule."""

    # --- no-local-augmented-mutation ---
    def test_no_local_augmented_mutation_local_var_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "x = 1\nx += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-local-augmented-mutation" for v in result.violations)

    def test_no_local_augmented_mutation_all_operators(self, tmp_path, full_semgrep_rules):
        """All 12 augmented assignment operators on local vars should be caught."""
        code = (
            "a = 1\na += 1\n"
            "b = 1\nb -= 1\n"
            "c = 1\nc *= 2\n"
            "d = 1\nd /= 2\n"
            "e = 1\ne //= 2\n"
            "f = 1\nf **= 2\n"
            "g = 10\ng %= 3\n"
            "h = 0xFF\nh &= 0x0F\n"
            "i = 0x0F\ni |= 0xF0\n"
            "j = 0xFF\nj ^= 0x0F\n"
            "k = 8\nk >>= 2\n"
            "l = 1\nl <<= 2\n"
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        local_violations = [v for v in result.violations if v.rule == "no-local-augmented-mutation"]
        assert len(local_violations) >= 12

    def test_no_local_augmented_mutation_attribute_pass(self, tmp_path, full_semgrep_rules):
        """obj.attr += val should NOT trigger no-local-augmented-mutation."""
        path = _make_file(tmp_path, "widget.py", "class C:\n    x = 0\nc = C()\nc.x += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-local-augmented-mutation" for v in result.violations)

    def test_no_local_augmented_mutation_subscript_pass(self, tmp_path, full_semgrep_rules):
        """obj[key] += val should NOT trigger no-local-augmented-mutation."""
        path = _make_file(tmp_path, "widget.py", "d = {'a': 1}\nd['a'] += 1\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-local-augmented-mutation" for v in result.violations)

    # --- no-none-default-param ---
    def test_no_none_default_param_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x=None):\n    return x\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-none-default-param" for v in result.violations)

    def test_no_none_default_param_multiple_params_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x, y=None, z=None):\n    return x\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-none-default-param" for v in result.violations)

    def test_no_none_default_param_non_none_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x=0, y=''):\n    return x\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-none-default-param" for v in result.violations)

    def test_no_none_default_param_assignment_outside_func_pass(self, tmp_path, full_semgrep_rules):
        """x = None outside function parameters should NOT trigger this rule."""
        path = _make_file(tmp_path, "widget.py", "x = None\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-none-default-param" for v in result.violations)

    # --- no-optional-none ---
    def test_no_optional_none_optional_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from typing import Optional\ndef f(x: Optional[str]):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_pipe_none_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x: str | None):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_none_pipe_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x: None | str):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_union_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from typing import Union\ndef f(x: Union[str, None]):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_union_reversed_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from typing import Union\ndef f(x: Union[None, str]):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_clean_type_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x: str):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-optional-none" for v in result.violations)

    def test_no_optional_none_union_without_none_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from typing import Union\ndef f(x: Union[str, int]):\n    pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-optional-none" for v in result.violations)


@needs_sg
class TestLoopMutationRule:
    """Tests for the no-loop-mutation ast-grep rule."""

    def test_append_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    result = []\n"
            "    for x in items:\n"
            "        result.append(x)\n"
            "    return result\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-loop-mutation" for v in result.violations)

    def test_extend_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(lists):\n"
            "    result = []\n"
            "    for lst in lists:\n"
            "        result.extend(lst)\n"
            "    return result\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_subscript_assign_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(d, keys, val):\n"
            "    for k in keys:\n"
            "        d[k] = val\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_augmented_assign_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    total = 0\n"
            "    for x in items:\n"
            "        total += x\n"
            "    return total\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_del_subscript_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(d, keys):\n"
            "    for k in keys:\n"
            "        del d[k]\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_set_add_in_for_fails(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    seen = set()\n"
            "    for x in items:\n"
            "        seen.add(x)\n"
            "    return seen\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False

    def test_no_mutation_in_for_passes(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    for x in items:\n"
            "        print(x)\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    def test_mutation_outside_for_passes(self, tmp_path, loop_mutation_rules_dir):
        path = _make_file(tmp_path, "widget.py",
            "def f(items):\n"
            "    result = []\n"
            "    result.append(42)\n"
            "    return result\n")
        gate = LintGate(rules_dir=loop_mutation_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True


@needs_semgrep
class TestSemgrepSimplePatternRules:
    """Comprehensive tests for simple-pattern Semgrep rules."""

    def test_no_list_append_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-append" for v in result.violations)

    def test_no_list_append_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1, 2, 3]\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-list-append" for v in result.violations)

    def test_no_list_extend_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.extend([1, 2])\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-extend" for v in result.violations)

    def test_no_list_extend_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1] + [2, 3]\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-list-extend" for v in result.violations)

    def test_no_list_insert_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [2, 3]\nitems.insert(0, 1)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-insert" for v in result.violations)

    def test_no_list_insert_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1] + [2, 3]\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-list-insert" for v in result.violations)

    def test_no_list_pop_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1, 2, 3]\nitems.pop(0)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-pop" for v in result.violations)

    def test_no_list_pop_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1, 2, 3]\nfirst, rest = items[0], items[1:]\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-list-pop" for v in result.violations)

    def test_no_list_remove_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [1, 2, 3]\nitems.remove(2)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-list-remove" for v in result.violations)

    def test_no_list_remove_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "items = [x for x in [1, 2, 3] if x != 2]\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-list-remove" for v in result.violations)

    def test_no_dict_clear_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {1: 2}\nd.clear()\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-dict-clear" for v in result.violations)

    def test_no_dict_clear_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-dict-clear" for v in result.violations)

    def test_no_dict_update_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd.update({1: 2})\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-dict-update" for v in result.violations)

    def test_no_dict_update_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {**a, **b}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-dict-update" for v in result.violations)

    def test_no_dict_setdefault_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd.setdefault('k', [])\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-dict-setdefault" for v in result.violations)

    def test_no_dict_setdefault_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "from collections import defaultdict\nd = defaultdict(list)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-dict-setdefault" for v in result.violations)

    def test_no_set_add_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "s = set()\ns.add(1)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-set-add" for v in result.violations)

    def test_no_set_add_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "s = {1} | {2}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-set-add" for v in result.violations)

    def test_no_set_discard_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "s = {1, 2}\ns.discard(1)\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-set-discard" for v in result.violations)

    def test_no_set_discard_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "s = {1, 2} - {1}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-set-discard" for v in result.violations)

    def test_no_subscript_mutation_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {}\nd['key'] = 'val'\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-mutation" for v in result.violations)

    def test_no_subscript_mutation_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {'key': 'val'}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-subscript-mutation" for v in result.violations)

    def test_no_subscript_del_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {'a': 1}\ndel d['a']\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-subscript-del" for v in result.violations)

    def test_no_subscript_del_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "d = {k: v for k, v in d.items() if k != 'a'}\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-subscript-del" for v in result.violations)

    def test_no_is_none_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x):\n    if x is None:\n        return 0\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-is-none" for v in result.violations)

    def test_no_is_none_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x):\n    if x == 0:\n        return 0\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-is-none" for v in result.violations)

    def test_no_is_not_none_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x):\n    if x is not None:\n        return x\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-is-not-none" for v in result.violations)

    def test_no_is_not_none_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "def f(x):\n    if x != 0:\n        return x\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-is-not-none" for v in result.violations)

    def test_no_print_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-print" for v in result.violations)

    def test_no_print_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "import logging\nlogging.info('hello')\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-print" for v in result.violations)

    def test_no_static_method_fail(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "class Foo:\n    @staticmethod\n    def bar():\n        pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "no-static-method" for v in result.violations)

    def test_no_static_method_pass(self, tmp_path, full_semgrep_rules):
        path = _make_file(tmp_path, "widget.py", "class Foo:\n    @classmethod\n    def bar(cls):\n        pass\n")
        gate = LintGate(rules_dir=full_semgrep_rules)
        result = gate.evaluate([path], str(tmp_path))
        assert not any(v.rule == "no-static-method" for v in result.violations)


@needs_semgrep
class TestLintGateDualBackend:
    """Integration tests for the dual-backend LintGate."""

    def test_no_violations_passes(self, tmp_path, dual_backend_rules_dir):
        path = _make_file(tmp_path, "widget.py", "def compute():\n    return 42\n")
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is True

    @needs_sg
    def test_both_backends_violations_merged(self, tmp_path, dual_backend_rules_dir):
        """File with Semgrep violation (.append) AND ast-grep violation (nested for)."""
        code = (
            "def f(matrix):\n"
            "    result = []\n"
            "    result.append(1)\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            pass\n"
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        rule_ids = [v.rule for v in result.violations]
        assert any("no-list-append" in r for r in rule_ids)
        assert any("no-deep-nesting" in r for r in rule_ids)

    def test_semgrep_only_violation(self, tmp_path, dual_backend_rules_dir):
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-list-append" for v in result.violations)

    @needs_sg
    def test_ast_grep_only_violation(self, tmp_path, dual_backend_rules_dir):
        code = (
            "def f(matrix):\n"
            "    for row in matrix:\n"
            "        for cell in row:\n"
            "            pass\n"
        )
        path = _make_file(tmp_path, "widget.py", code)
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-deep-nesting" for v in result.violations)

    def test_semgrep_missing_fails_gate(self, tmp_path, dual_backend_rules_dir, monkeypatch):
        path = _make_file(tmp_path, "widget.py", "x = 1\n")
        monkeypatch.setattr(shutil, "which", lambda _: None)
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any("semgrep" in v.message.lower() for v in result.violations)

    def test_ast_grep_missing_semgrep_still_works(self, tmp_path, dual_backend_rules_dir, monkeypatch):
        """When ast-grep is missing, Semgrep violations are still reported."""
        original_which = shutil.which
        monkeypatch.setattr(shutil, "which", lambda cmd: None if cmd in ("sg", "ast-grep") else original_which(cmd))
        path = _make_file(tmp_path, "widget.py", "items = []\nitems.append(1)\n")
        gate = LintGate(rules_dir=dual_backend_rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert result.passed is False
        assert any(v.rule == "no-list-append" for v in result.violations)
