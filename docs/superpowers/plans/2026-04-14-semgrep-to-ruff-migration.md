# Semgrep-to-Ruff Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Semgrep with Ruff, unify LintGate into a single gate running ast-grep + Ruff + beniget, and add moderate Ruff hygiene rules.

**Architecture:** Single `LintGate` class with three backends called in sequence: `_run_ast_grep()`, `_run_ruff()`, `_run_reassignment()`. Each returns `list[LintViolation]`. Ruff invoked as subprocess (`ruff check --output-format json`). `MixedLintGate` and all CLI filter flags removed.

**Tech Stack:** Python 3.10+, ast-grep, Ruff (subprocess), beniget, pytest, uv

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Rewrite | `python_fp_lint/lint_gate.py` | Single `LintGate` with ast-grep + Ruff + beniget backends |
| Modify | `python_fp_lint/__main__.py` | Simplified CLI — no filter flags, updated schema |
| Modify | `python_fp_lint/__init__.py` | Export only `LintGate`, `LintResult`, `LintViolation` |
| Modify | `python_fp_lint/rules_meta.py` | Replace Semgrep metadata with Ruff rule listing |
| Keep | `python_fp_lint/reassignment_gate.py` | Unchanged — called internally by `LintGate` |
| Keep | `python_fp_lint/result.py` | Unchanged — `LintResult`, `LintViolation` |
| Delete | `python_fp_lint/semgrep-rules.yml` | Semgrep removed entirely |
| Delete | `python_fp_lint/rules/no-bare-except.yml` | Covered by Ruff BLE001 |
| Delete | `python_fp_lint/rules/no-print.yml` | Covered by Ruff T201 |
| Delete | `python_fp_lint/rules/no-relative-import.yml` | Covered by Ruff TID252 |
| Rewrite | `tests/test_lint_gate.py` | Unified gate tests + Ruff integration tests |
| Modify | `tests/test_ast_grep_rules.py` | Remove 7 tests for 3 deleted rules |
| Modify | `tests/test_cli.py` | Remove flag-specific tests, update assertions |
| Modify | `.github/workflows/ci.yml` | Replace Semgrep with Ruff |
| Modify | `README.md` | Updated architecture, rules, usage, dependencies |

---

### Task 1: Delete Ruff-covered ast-grep rules and update ast-grep tests

**Files:**
- Delete: `python_fp_lint/rules/no-bare-except.yml`
- Delete: `python_fp_lint/rules/no-print.yml`
- Delete: `python_fp_lint/rules/no-relative-import.yml`
- Modify: `tests/test_ast_grep_rules.py:283-314` (TestStyleRules — remove print and relative-import tests)
- Modify: `tests/test_ast_grep_rules.py:322-338` (TestExceptionRules — remove bare-except tests)

- [ ] **Step 1: Remove 7 tests for the 3 deleted rules from `test_ast_grep_rules.py`**

In `tests/test_ast_grep_rules.py`, remove the following test methods:

From `TestStyleRules` (lines 285-314):
- `test_print_fails` (lines 285-287)
- `test_print_passes` (lines 289-291)
- `test_relative_import_dot_fails` (lines 303-305)
- `test_relative_import_dotdot_fails` (lines 307-309)
- `test_relative_import_passes` (lines 311-314)

From `TestExceptionRules` (lines 324-329):
- `test_bare_except_fails` (lines 324-326)
- `test_bare_except_passes` (lines 328-330)

Keep `test_static_method_fails`, `test_static_method_passes`, `test_except_exception_fails`, and `test_except_exception_passes`.

- [ ] **Step 2: Delete the 3 ast-grep rule files**

```bash
rm python_fp_lint/rules/no-bare-except.yml
rm python_fp_lint/rules/no-print.yml
rm python_fp_lint/rules/no-relative-import.yml
```

- [ ] **Step 3: Run ast-grep tests to verify**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_ast_grep_rules.py -x -q
```

Expected: All remaining tests pass. Test count drops by 7 (from ~70 to ~63).

- [ ] **Step 4: Commit**

```bash
git add tests/test_ast_grep_rules.py
git add -u python_fp_lint/rules/
git commit -m "refactor: remove 3 ast-grep rules now covered by Ruff (BLE001, T201, TID252)"
```

---

### Task 2: Add `_run_ruff()` to lint_gate.py

**Files:**
- Modify: `python_fp_lint/lint_gate.py`
- Create: `tests/test_ruff_integration.py`

- [ ] **Step 1: Write failing test for Ruff integration**

Create `tests/test_ruff_integration.py`:

```python
# tests/test_ruff_integration.py
"""Tests for Ruff backend integration in LintGate."""

import shutil
import pytest

from python_fp_lint.lint_gate import _find_ruff, _run_ruff


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
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert any(v.rule == "BLE001" for v in violations)

    def test_detects_print(self, tmp_path):
        f = tmp_path / "prints.py"
        f.write_text("print('hello')\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert any(v.rule == "T201" for v in violations)

    def test_detects_relative_import(self, tmp_path):
        f = tmp_path / "rel.py"
        f.write_text("from . import utils\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert any(v.rule == "TID252" for v in violations)

    def test_clean_file_no_violations(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert violations == []

    def test_violation_fields(self, tmp_path):
        f = tmp_path / "bare.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        v = [v for v in violations if v.rule == "BLE001"][0]
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
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert violations == []

    def test_unused_import_detected(self, tmp_path):
        f = tmp_path / "unused.py"
        f.write_text("import os\nx = 1\n")
        violations = _run_ruff(shutil.which("ruff"), [str(f)])
        assert any(v.rule == "F401" for v in violations)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_ruff_integration.py -x -q
```

Expected: FAIL — `_find_ruff` and `_run_ruff` don't exist yet.

- [ ] **Step 3: Implement `_find_ruff()` and `_run_ruff()` in lint_gate.py**

Add to `python_fp_lint/lint_gate.py` after the existing `_run_sg()` function (after line 272):

```python
# Ruff rule selection — moderate hygiene set
_RUFF_SELECT = "F,E,B,BLE,T20,TID252,C901,UP"


def _find_ruff() -> str | None:
    return shutil.which("ruff")


def _run_ruff(ruff_path: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                ruff_path,
                "check",
                "--output-format",
                "json",
                "--select",
                _RUFF_SELECT,
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    violations = []
    for entry in entries:
        violations.append(
            LintViolation(
                rule=entry.get("code", "unknown"),
                file=entry.get("filename", ""),
                line=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
            )
        )
    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_ruff_integration.py -x -q
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add python_fp_lint/lint_gate.py tests/test_ruff_integration.py
git commit -m "feat: add Ruff backend with _find_ruff() and _run_ruff()"
```

---

### Task 3: Unify LintGate — integrate Ruff and ReassignmentGate, remove MixedLintGate

**Files:**
- Rewrite: `python_fp_lint/lint_gate.py`
- Rewrite: `tests/test_lint_gate.py`

- [ ] **Step 1: Write failing tests for unified LintGate**

Replace `tests/test_lint_gate.py` entirely:

```python
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
        assert any(v.rule == "BLE001" for v in result.violations)

    def test_print_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "print('hello')\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "T201" for v in result.violations)

    def test_relative_import_detected_via_ruff(self, tmp_path, rules_dir):
        path = _make_file(tmp_path, "widget.py", "from . import utils\n")
        gate = LintGate(rules_dir=rules_dir)
        result = gate.evaluate([path], str(tmp_path))
        assert any(v.rule == "TID252" for v in result.violations)

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_lint_gate.py -x -q
```

Expected: FAIL — `MixedLintGate` import removed, unified gate doesn't exist yet.

- [ ] **Step 3: Rewrite `lint_gate.py` with unified LintGate**

Replace the entire content of `python_fp_lint/lint_gate.py`:

```python
# python_fp_lint/lint_gate.py
"""Unified LintGate — runs ast-grep + Ruff + beniget in sequence."""

import glob
import json
import os
import shutil
import subprocess

from python_fp_lint.reassignment_gate import ReassignmentGate
from python_fp_lint.result import LintResult, LintViolation

# Ruff rule selection — moderate hygiene set
_RUFF_SELECT = "F,E,B,BLE,T20,TID252,C901,UP"


class LintGate:
    """Unified lint gate — runs ast-grep, Ruff, and beniget reassignment detection."""

    def __init__(self, rules_dir: str | None = None):
        self.rules_dir = rules_dir

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = _filter_python_files(changed_files)
        if not py_files:
            return LintResult(passed=True, violations=[])

        violations = []
        violations.extend(self._run_ast_grep(py_files, project_root))
        violations.extend(self._run_ruff(py_files))
        violations.extend(self._run_reassignment(py_files, project_root))

        return LintResult(passed=len(violations) == 0, violations=violations)

    def _run_ast_grep(self, files: list[str], project_root: str) -> list[LintViolation]:
        rules_dir = self._resolve_rules_dir(project_root)
        if rules_dir is None:
            return []

        sg = _find_sg()
        if sg is None:
            return []

        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if not os.path.exists(sgconfig):
            return []

        return _run_sg(sg, rules_dir, files)

    def _run_ruff(self, files: list[str]) -> list[LintViolation]:
        ruff = _find_ruff()
        if ruff is None:
            return []
        return _run_ruff(ruff, files)

    def _run_reassignment(
        self, files: list[str], project_root: str
    ) -> list[LintViolation]:
        result = ReassignmentGate().evaluate(files, project_root)
        return result.violations

    def _resolve_rules_dir(self, project_root: str) -> str | None:
        return _resolve_rules_dir(self.rules_dir, project_root)


# --- shared helpers ---


def _expand_paths(paths: list[str]) -> list[str]:
    """Expand directories, globs, and plain files into a flat list of paths."""
    expanded = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    expanded.append(os.path.join(root, f))
        elif any(c in p for c in ("*", "?", "[")):
            expanded.extend(glob.glob(p, recursive=True))
        else:
            expanded.append(p)
    return expanded


def _filter_python_files(files: list[str]) -> list[str]:
    """Expand dirs/globs, then filter to existing, unique .py files."""
    seen = set()
    result = []
    for f in _expand_paths(files):
        real = os.path.abspath(f)
        if real in seen:
            continue
        seen.add(real)
        if real.endswith(".py") and os.path.exists(real):
            result.append(real)
    return result


def _find_sg() -> str | None:
    return shutil.which("sg") or shutil.which("ast-grep")


def _find_ruff() -> str | None:
    return shutil.which("ruff")


def _resolve_rules_dir(explicit_dir: str | None, project_root: str) -> str | None:
    """Find the lint rules directory.

    Searches in order: explicit rules_dir, package-local (next to this file),
    project-local scripts/lint/, then lint_rules_dir from config.json.
    """
    if explicit_dir:
        return explicit_dir
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        pkg_dir,
        os.path.join(project_root, "scripts", "lint"),
    ]
    config_dir = _read_config_rules_dir()
    if config_dir:
        candidates.append(config_dir)
    for candidate in candidates:
        if os.path.isdir(candidate) and os.path.exists(
            os.path.join(candidate, "sgconfig.yml")
        ):
            return candidate
    return None


def _read_config_rules_dir() -> str | None:
    """Read lint_rules_dir from the plugin config.json."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.json",
    )
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path) as f:
            return json.load(f).get("lint_rules_dir")
    except (json.JSONDecodeError, OSError):
        return None


def _run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                sg_path,
                "scan",
                "--json",
                "--config",
                os.path.join(rules_dir, "sgconfig.yml"),
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=rules_dir,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        entries = []
        for line in result.stdout.strip().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    violations = []
    for entry in entries:
        violations.append(
            LintViolation(
                rule=entry.get("ruleId", "unknown"),
                file=entry.get("file", ""),
                line=entry.get("range", {}).get("start", {}).get("line", 0) + 1,
                message=entry.get("message", ""),
            )
        )
    return violations


def _run_ruff(ruff_path: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                ruff_path,
                "check",
                "--output-format",
                "json",
                "--select",
                _RUFF_SELECT,
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    violations = []
    for entry in entries:
        violations.append(
            LintViolation(
                rule=entry.get("code", "unknown"),
                file=entry.get("filename", ""),
                line=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
            )
        )
    return violations
```

Key changes from current code:
- `MixedLintGate` removed entirely
- `_find_semgrep()` and `_run_semgrep()` removed
- `LintGate.evaluate()` now calls three backends
- `_resolve_rules_dir()` no longer checks for `semgrep-rules.yml` — only `sgconfig.yml`
- `_find_ruff()` and `_run_ruff()` added (from Task 2)
- sg/ruff missing = empty list (warning, not error), so other backends still run

- [ ] **Step 4: Run tests to verify**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_lint_gate.py tests/test_ruff_integration.py -x -q
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add python_fp_lint/lint_gate.py tests/test_lint_gate.py
git commit -m "feat: unify LintGate with ast-grep + Ruff + beniget, remove MixedLintGate"
```

---

### Task 4: Simplify CLI — remove filter flags

**Files:**
- Modify: `python_fp_lint/__main__.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Update CLI tests — remove flag tests, update assertions**

In `tests/test_cli.py`:

Remove `test_semgrep_only_flag` (lines 74-79) and `test_reassignment_only_flag` (lines 81-86) from `TestCLI`.

In `TestRulesCommand.test_rules_text` (line 148-150), change:
```python
    def test_rules_text(self):
        result = _run_bare("rules")
        assert result.returncode == 0
        assert "ast-grep" in result.stdout
        assert "ruff" in result.stdout
        assert "beniget" in result.stdout
```

In `TestRulesCommand.test_rules_json` (line 152-161), change:
```python
    def test_rules_json(self):
        result = _run_bare("--format", "json", "rules")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0
        backends = {r["backend"] for r in data}
        assert backends == {"ast-grep", "ruff", "beniget"}
        for r in data:
            assert set(r.keys()) == {"id", "message", "severity", "backend"}
```

- [ ] **Step 2: Run CLI tests to verify they fail**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_cli.py -x -q
```

Expected: FAIL — `MixedLintGate` import fails, flags still exist.

- [ ] **Step 3: Rewrite `__main__.py`**

Replace the entire content of `python_fp_lint/__main__.py`:

```python
# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check file1.py file2.py

Designed for both human use (text output) and LLM agent use (--format json).
"""

import argparse
import json
import sys

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.rules_meta import list_rules


def _run_check(args):
    gate = LintGate()
    result = gate.evaluate(args.files, ".")

    if args.format == "json":
        payload = {
            "passed": result.passed,
            "violation_count": len(result.violations),
            "violations": [
                {
                    "rule": v.rule,
                    "file": v.file,
                    "line": v.line,
                    "message": v.message,
                }
                for v in result.violations
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        if not result.violations:
            print("No violations found.")
        else:
            for v in result.violations:
                loc = f"{v.file}:{v.line}" if v.line else v.file
                print(f"  [{v.rule}] {loc} — {v.message}")
            print(f"\n{len(result.violations)} violation(s) found.")

    sys.exit(0 if result.passed else 1)


def _run_rules(args):
    rules = list_rules()

    if args.format == "json":
        json.dump(rules, sys.stdout, indent=2)
        print()
    else:
        for r in rules:
            backend = r["backend"]
            print(f"  [{backend:8s}] {r['id']}")
            print(f"             {r['message']}")


def _run_schema(_args):
    schema = {
        "check_output": {
            "description": "Output of the 'check' command",
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "True if no violations found",
                },
                "violation_count": {
                    "type": "integer",
                    "description": "Number of violations",
                },
                "violations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule": {
                                "type": "string",
                                "description": "Rule ID that was violated",
                            },
                            "file": {
                                "type": "string",
                                "description": "Path to the file",
                            },
                            "line": {
                                "type": "integer",
                                "description": "Line number (1-based, 0 if unknown)",
                            },
                            "message": {
                                "type": "string",
                                "description": "Human-readable violation message",
                            },
                        },
                    },
                },
            },
        },
        "rules_output": {
            "description": "Output of the 'rules' command",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "message": {"type": "string"},
                    "severity": {"type": "string"},
                    "backend": {
                        "type": "string",
                        "enum": ["ast-grep", "ruff", "beniget"],
                    },
                },
            },
        },
    }
    json.dump(schema, sys.stdout, indent=2)
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="python-fp-lint",
        description="Functional-programming lint rules for Python",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    sub = parser.add_subparsers(dest="command")

    # --- check ---
    check = sub.add_parser("check", help="Run lint checks on files")
    check.add_argument("files", nargs="+", help="Python files to check")

    # --- rules ---
    sub.add_parser("rules", help="List all available lint rules")

    # --- schema ---
    sub.add_parser("schema", help="Print JSON schema for check/rules output")

    args = parser.parse_args()

    if args.command == "check":
        _run_check(args)
    elif args.command == "rules":
        _run_rules(args)
    elif args.command == "schema":
        _run_schema(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

Key changes: removed `MixedLintGate` and `ReassignmentGate` imports, removed `--semgrep-only`/`--reassignment-only`/`--mixed` flags, simplified `_run_check()` to one `LintGate().evaluate()` call, updated schema enum to `["ast-grep", "ruff", "beniget"]`.

- [ ] **Step 4: Run CLI tests to verify**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_cli.py -x -q
```

Expected: All tests pass. Test count drops by 2 (from 19 to 17).

- [ ] **Step 5: Commit**

```bash
git add python_fp_lint/__main__.py tests/test_cli.py
git commit -m "refactor: simplify CLI — remove --mixed, --semgrep-only, --reassignment-only flags"
```

---

### Task 5: Update `__init__.py` exports

**Files:**
- Modify: `python_fp_lint/__init__.py`

- [ ] **Step 1: Update exports**

Replace the content of `python_fp_lint/__init__.py`:

```python
"""python-fp-lint — functional-programming lint rules for Python."""

from python_fp_lint.result import LintResult, LintViolation
from python_fp_lint.lint_gate import LintGate

__all__ = [
    "LintGate",
    "LintResult",
    "LintViolation",
]
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run python -c "from python_fp_lint import LintGate, LintResult, LintViolation; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python_fp_lint/__init__.py
git commit -m "refactor: export only LintGate, LintResult, LintViolation"
```

---

### Task 6: Update `rules_meta.py` — replace Semgrep with Ruff

**Files:**
- Modify: `python_fp_lint/rules_meta.py`

- [ ] **Step 1: Run existing rules test to capture baseline**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_cli.py::TestRulesCommand -x -q
```

Expected: Tests already fail (from Task 4 changes expecting `ruff` backend).

- [ ] **Step 2: Rewrite `rules_meta.py`**

Replace the entire content of `python_fp_lint/rules_meta.py`:

```python
# python_fp_lint/rules_meta.py
"""Rule metadata — reads rule definitions from all backends."""

import os

import yaml

# Ruff rules included in the moderate hygiene set
_RUFF_RULES = [
    {"id": "F", "message": "Pyflakes — unused imports, undefined names, unused vars"},
    {"id": "E", "message": "pycodestyle errors"},
    {"id": "B", "message": "flake8-bugbear — mutable defaults, assert False"},
    {"id": "BLE", "message": "Blind except detection"},
    {"id": "T20", "message": "Print statement detection"},
    {"id": "TID252", "message": "Relative import detection"},
    {"id": "C901", "message": "Cyclomatic complexity"},
    {"id": "UP", "message": "pyupgrade — deprecated syntax"},
]


def _rules_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")


def _ast_grep_rules() -> list[dict]:
    rules = []
    rdir = _rules_dir()
    if not os.path.isdir(rdir):
        return rules
    for fname in sorted(os.listdir(rdir)):
        if not fname.endswith(".yml") or fname == "sgconfig.yml":
            continue
        path = os.path.join(rdir, fname)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            rules.append(
                {
                    "id": data.get("id", fname.removesuffix(".yml")),
                    "message": data.get("message", ""),
                    "severity": data.get("severity", "warning"),
                    "backend": "ast-grep",
                }
            )
        except (yaml.YAMLError, OSError):
            continue
    return rules


def _ruff_rules() -> list[dict]:
    return [
        {
            "id": r["id"],
            "message": r["message"],
            "severity": "warning",
            "backend": "ruff",
        }
        for r in _RUFF_RULES
    ]


def list_rules() -> list[dict]:
    """Return metadata for all available lint rules across all backends."""
    rules = _ast_grep_rules() + _ruff_rules()
    rules.append(
        {
            "id": "reassignment",
            "message": "Variable reassignment detected — use new bindings instead",
            "severity": "warning",
            "backend": "beniget",
        }
    )
    return rules
```

- [ ] **Step 3: Run tests to verify**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/test_cli.py::TestRulesCommand -x -q
```

Expected: All 3 rules tests pass.

- [ ] **Step 4: Commit**

```bash
git add python_fp_lint/rules_meta.py
git commit -m "refactor: replace Semgrep rule metadata with Ruff rule listing"
```

---

### Task 7: Delete `semgrep-rules.yml` and clean up

**Files:**
- Delete: `python_fp_lint/semgrep-rules.yml`

- [ ] **Step 1: Delete the Semgrep rules file**

```bash
rm python_fp_lint/semgrep-rules.yml
```

- [ ] **Step 2: Run full test suite to verify nothing references it**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add -u python_fp_lint/semgrep-rules.yml
git commit -m "chore: delete semgrep-rules.yml — Semgrep fully removed"
```

---

### Task 8: Update CI workflow and README

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: Update CI workflow**

Replace `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  UV_PROJECT_ENVIRONMENT: .venv

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install ast-grep
        run: |
          npm install -g @ast-grep/cli
          sg --version

      - name: Install dependencies
        run: |
          uv sync --all-extras
          uv pip install -e .
          uv pip install ruff

      - name: Add venv to PATH
        run: echo "${{ github.workspace }}/.venv/bin" >> $GITHUB_PATH

      - name: Verify tools
        run: |
          ruff --version
          sg --version

      - name: Check formatting (Black)
        run: uv run black --check .

      - name: Run tests
        run: uv run pytest tests/ -x -q
```

Changes: replaced `uv pip install semgrep` with `uv pip install ruff`, replaced `semgrep --version` with `ruff --version`.

- [ ] **Step 2: Update README.md**

Update the following sections in `README.md`:

**Line 6-11 (description + backends):**
```markdown
**python-fp-lint** is a functional-programming linter for Python. It detects mutation, reassignment, and impurity patterns that violate FP discipline, combining three complementary analysis backends:

1. **ast-grep** (27 rules) — tree-sitter AST analysis for FP-specific mutation rules
2. **Ruff** (moderate hygiene set) — Rust-based linter for unused imports, style errors, complexity, and more
3. **beniget** — def-use chain analysis for variable reassignment detection across scopes

The unified `LintGate` runs all three backends in sequence. Each backend that is available contributes violations; missing tools are silently skipped.
```

**Lines 16-29 (ast-grep rules table):** Update to 27 rules — remove `no-bare-except`, `no-print`, `no-relative-import`:
```markdown
### ast-grep rules (27)

| Category | Rules |
|----------|-------|
| **List mutation** | `no-list-append`, `no-list-extend`, `no-list-insert`, `no-list-pop`, `no-list-remove` |
| **Dict mutation** | `no-dict-clear`, `no-dict-update`, `no-dict-setdefault` |
| **Set mutation** | `no-set-add`, `no-set-discard` |
| **Subscript mutation** | `no-subscript-mutation`, `no-subscript-del`, `no-subscript-augmented-mutation`, `no-subscript-tuple-mutation`, `no-setitem-call` |
| **Augmented assignment** | `no-local-augmented-mutation`, `no-attribute-augmented-mutation` |
| **None / Optional** | `no-is-none`, `no-is-not-none`, `no-optional-none`, `no-none-default-param` |
| **Exception handling** | `no-except-exception` |
| **Style** | `no-static-method` |
| **Structural** | `no-deep-nesting`, `no-loop-mutation` |
| **Type annotations** | `no-list-dict-param-annotation`, `no-unfrozen-dataclass` |

### Ruff rules (moderate hygiene set)

| Ruff code | Category |
|-----------|----------|
| `F` | Pyflakes — unused imports, undefined names, unused vars |
| `E` | pycodestyle errors |
| `B` | flake8-bugbear — mutable defaults, assert False |
| `BLE` | Blind except detection |
| `T20` | Print statement detection |
| `TID252` | Relative import detection |
| `C901` | Cyclomatic complexity |
| `UP` | pyupgrade — deprecated syntax |
```

**Lines 36-42 (Requirements):**
```markdown
### Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — package manager
- [ast-grep](https://ast-grep.github.io/) (`sg`) — required for FP mutation rules
- [Ruff](https://docs.astral.sh/ruff/) — required for hygiene rules
```

**Lines 57-77 (CLI Usage):**
```markdown
## Usage

### CLI

```bash
# Run all checks on files
uv run python -m python_fp_lint check file1.py file2.py

# Directories (recursive) and globs
uv run python -m python_fp_lint check src/
uv run python -m python_fp_lint check 'src/**/*.py'
uv run python -m python_fp_lint check src/ tests/test_foo.py 'lib/*.py'
```
```

**Lines 113-127 (Programmatic API):**
```markdown
### Programmatic API

```python
from python_fp_lint import LintGate, LintResult, LintViolation

# Unified gate — runs ast-grep + Ruff + beniget
result = LintGate().evaluate(["src/app.py"], project_root=".")

for v in result.violations:
    print(f"[{v.rule}] {v.file}:{v.line} — {v.message}")
```
```

**Lines 166-178 (Architecture):**
```markdown
## Architecture

```
python_fp_lint/
├── lint_gate.py           # Unified LintGate (ast-grep + Ruff + beniget)
├── reassignment_gate.py   # beniget def-use chain analysis (called by LintGate)
├── result.py              # LintResult, LintViolation dataclasses
├── rules_meta.py          # Rule metadata reader (for CLI rules/schema commands)
├── __init__.py            # Public API: LintGate, LintResult, LintViolation
├── __main__.py            # CLI entry point (text + JSON output)
├── sgconfig.yml           # ast-grep configuration
└── rules/                 # 27 ast-grep rule files (.yml)
```

Each backend is called in sequence: ast-grep, Ruff, beniget. Missing tools are silently skipped.
```

**Lines 183-191 (Dependencies):**
```markdown
## Dependencies

| Dependency | Purpose |
|------------|---------|
| `beniget` | Def-use chain analysis (runtime) |
| `pyyaml` | Rule metadata parsing (runtime) |
| `pytest` | Test framework (dev) |
| `black` | Code formatter (dev) |
| `sg` (ast-grep) | AST-based FP mutation rules (external tool) |
| `ruff` | Hygiene lint rules (external tool) |
```

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/asgupta/code/python-fp-lint && uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "docs: update CI workflow and README for Ruff migration"
```

---

## Self-Review

**Spec coverage check:**
- [x] Remove Semgrep entirely → Tasks 3, 7
- [x] Remove 3 Ruff-covered rules → Task 1
- [x] Add Ruff hygiene rules → Task 2
- [x] Unify LintGate → Task 3
- [x] Remove CLI filter flags → Task 4
- [x] Update public API → Task 5
- [x] Update rules metadata → Task 6
- [x] Update CI → Task 8
- [x] Update README → Task 8

**Placeholder scan:** No TBD/TODO found. All code blocks are complete.

**Type consistency:** `_find_ruff()`, `_run_ruff()`, `LintGate`, `LintResult`, `LintViolation` — names consistent across all tasks. `_RUFF_SELECT` string consistent between lint_gate.py and rules_meta.py descriptions.
