# Semgrep→Ruff Migration Design

**Goal:** Replace Semgrep with Ruff, unify LintGate into a single gate running ast-grep + Ruff + beniget, and add moderate Ruff hygiene rules.

## Context

python-fp-lint currently has three lint backends:

- **ast-grep** (30 rules) — tree-sitter AST analysis for FP-specific mutation rules
- **Semgrep** (26 rules) — pattern matching alternative, used by `MixedLintGate`
- **beniget** — def-use chain analysis for variable reassignment detection

The 26 Semgrep rules are a near-complete subset of the 30 ast-grep rules. `MixedLintGate` exists only because Semgrep was the original backend; ast-grep replaced it for speed. Semgrep adds no unique value.

Ruff is a Rust-based Python linter with 954 rules, all free and open-source. Three python-fp-lint rules are fully covered by Ruff (`no-bare-except`, `no-print`, `no-relative-import`). Ruff also provides hundreds of hygiene rules that Semgrep's free tier paywalls.

## Design

### Unified LintGate

One `LintGate` class replaces both `LintGate` and `MixedLintGate`. It runs three backends in sequence:

1. **ast-grep** (27 rules) — current 30 rules minus 3 Ruff-covered ones
2. **Ruff** (subprocess, `ruff check --output-format json`) — moderate hygiene ruleset
3. **beniget** (reassignment) — unchanged, called internally

```python
class LintGate:
    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        files = self._filter_python_files(changed_files, project_root)
        if not files:
            return LintResult(passed=True, violations=[])

        violations = []
        violations.extend(self._run_ast_grep(files))
        violations.extend(self._run_ruff(files))
        violations.extend(self._run_reassignment(files))

        return LintResult(passed=len(violations) == 0, violations=violations)
```

Each `_run_*` method returns `list[LintViolation]`. Tool-missing scenarios (no `sg` binary, no `ruff` binary) log a warning and return empty lists, same as current behavior.

### Ruff invocation

Subprocess call, consistent with ast-grep pattern:

```
ruff check --output-format json --select F,E,B,BLE,T20,TID252,C901,UP <files>
```

Binary found via `shutil.which("ruff")`. Timeout: 30 seconds.

### Ruff rule selection (moderate)

| Ruff code | Category | Replaces |
|-----------|----------|----------|
| `F` | Pyflakes — unused imports, undefined names, unused vars | — |
| `E` | pycodestyle errors | — |
| `B` | flake8-bugbear — mutable defaults, assert False | — |
| `BLE` | blind except | `no-bare-except` |
| `T20` | print detection | `no-print` |
| `TID252` | relative imports | `no-relative-import` |
| `C901` | cyclomatic complexity | — |
| `UP` | pyupgrade — deprecated syntax | — |

### Ruff JSON output parsing

Ruff's `--output-format json` produces:

```json
[
  {
    "code": "F401",
    "message": "`os` imported but unused",
    "filename": "/path/to/file.py",
    "location": {"row": 1, "column": 1},
    "end_location": {"row": 1, "column": 10}
  }
]
```

Maps to `LintViolation(rule=code, file=filename, line=location.row, message=message)`.

### Rule ID namespacing

- ast-grep rules: keep existing IDs (`no-list-append`, `no-deep-nesting`, etc.)
- Ruff rules: use Ruff codes directly (`F401`, `BLE001`, `T201`, etc.)
- beniget: keep `reassignment` ID

No prefix needed — the namespaces don't collide.

### Removals

| What | Why |
|------|-----|
| `MixedLintGate` class | Replaced by unified `LintGate` |
| `semgrep-rules.yml` | Semgrep removed entirely |
| `rules/no-bare-except.yml` | Covered by Ruff `BLE001` |
| `rules/no-print.yml` | Covered by Ruff `T201` |
| `rules/no-relative-import.yml` | Covered by Ruff `TID252` |
| `--mixed` CLI flag | One gate, no choice |
| `--semgrep-only` CLI flag | Semgrep gone |
| `--reassignment-only` CLI flag | No filtering, always run all |
| Semgrep CI install | No longer needed |

### Public API change

Before:
```python
from python_fp_lint import LintGate, MixedLintGate, ReassignmentGate
```

After:
```python
from python_fp_lint import LintGate, LintResult, LintViolation
```

`ReassignmentGate` still exists as a module but is no longer part of the public API. `LintGate` calls it internally.

### CLI simplification

Before:
```bash
python -m python_fp_lint check [--mixed] [--semgrep-only] [--reassignment-only] <files>
```

After:
```bash
python -m python_fp_lint check <files>
```

`--format json` and the `rules`/`schema` commands remain unchanged. The `rules` command output lists rules with backends: `ast-grep`, `ruff`, `beniget`.

### File changes

| Action | File | What |
|--------|------|------|
| Rewrite | `lint_gate.py` | Single `LintGate` with ast-grep + ruff + beniget |
| Modify | `__main__.py` | Remove filter flags, always run unified gate |
| Modify | `__init__.py` | Remove `MixedLintGate`, `ReassignmentGate` exports |
| Modify | `rules_meta.py` | Replace Semgrep metadata with Ruff rule listing |
| Delete | `semgrep-rules.yml` | Semgrep removed |
| Delete | `rules/no-bare-except.yml` | Covered by Ruff BLE001 |
| Delete | `rules/no-print.yml` | Covered by Ruff T201 |
| Delete | `rules/no-relative-import.yml` | Covered by Ruff TID252 |
| Rewrite | `tests/test_lint_gate.py` | Unified gate tests, Ruff integration tests |
| Modify | `tests/test_cli.py` | Remove flag-specific tests |
| Modify | `tests/test_ast_grep_rules.py` | Remove 3 deleted rule tests |
| Modify | `.github/workflows/ci.yml` | Remove Semgrep install, add Ruff install |
| Modify | `README.md` | Update architecture, rules, usage, dependencies |

### What stays the same

- `LintResult` / `LintViolation` dataclasses
- `ReassignmentGate` internals (just called by `LintGate` now)
- `evaluate()` method signature
- `sgconfig.yml` and `rules/` directory structure
- JSON output format for `check` command
- `rules` and `schema` CLI commands (content updated)
