# python-fp-lint

[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE.md)

**python-fp-lint** is a functional-programming linter for Python. It detects mutation, reassignment, and impurity patterns that violate FP discipline, combining three complementary analysis backends:

1. **ast-grep** (28 rules) — tree-sitter AST analysis for all lint rules, ~150x faster than Semgrep
2. **Semgrep** (26 rules) — pattern matching alternative, used by `MixedLintGate`
3. **beniget** — def-use chain analysis for variable reassignment detection across scopes

The default `LintGate` runs all 28 rules through ast-grep alone. `MixedLintGate` is available for environments that prefer Semgrep, adding ast-grep only for the two rules Semgrep cannot express (deep nesting, loop mutation).

## Rules

### ast-grep rules (28)

| Category | Rules |
|----------|-------|
| **List mutation** | `no-list-append`, `no-list-extend`, `no-list-insert`, `no-list-pop`, `no-list-remove` |
| **Dict mutation** | `no-dict-clear`, `no-dict-update`, `no-dict-setdefault` |
| **Set mutation** | `no-set-add`, `no-set-discard` |
| **Subscript mutation** | `no-subscript-mutation`, `no-subscript-del`, `no-subscript-augmented-mutation`, `no-subscript-tuple-mutation`, `no-setitem-call` |
| **Augmented assignment** | `no-local-augmented-mutation`, `no-attribute-augmented-mutation` |
| **None / Optional** | `no-is-none`, `no-is-not-none`, `no-optional-none`, `no-none-default-param` |
| **Exception handling** | `no-bare-except`, `no-except-exception` |
| **Style** | `no-print`, `no-static-method`, `no-relative-import` |
| **Structural** | `no-deep-nesting`, `no-loop-mutation` |

### Reassignment detection (beniget)

Detects variable and parameter reassignment within a single scope using def-use chain analysis. Tracks violations per scope (module, function, class).

## Setup

### Requirements

- Python 3.10+
- [ast-grep](https://ast-grep.github.io/) (`sg`) — required for `LintGate` (default)
- [Semgrep](https://semgrep.dev/) — required only for `MixedLintGate`

### Install

```bash
pip install -e ".[dev]"
```

Or install just the library:

```bash
pip install -e .
```

## Usage

### CLI

```bash
# Run all checks on files
python -m python_fp_lint check file1.py file2.py

# Directories (recursive) and globs
python -m python_fp_lint check src/
python -m python_fp_lint check 'src/**/*.py'
python -m python_fp_lint check src/ tests/test_foo.py 'lib/*.py'

# Semgrep + ast-grep rules only (no reassignment check)
python -m python_fp_lint check --semgrep-only file1.py

# Reassignment checks only
python -m python_fp_lint check --reassignment-only file1.py

# Use MixedLintGate (Semgrep + ast-grep) instead of pure ast-grep
python -m python_fp_lint check --mixed src/
```

### JSON output (for LLM agents and toolchains)

```bash
# Lint check with structured output
python -m python_fp_lint --format json check src/

# List all available rules
python -m python_fp_lint --format json rules

# Get JSON schema for output formats
python -m python_fp_lint schema
```

JSON check output:

```json
{
  "passed": false,
  "violation_count": 2,
  "violations": [
    {
      "rule": "no-list-append",
      "file": "src/app.py",
      "line": 12,
      "message": "list.append() — use list concatenation or comprehension"
    }
  ]
}
```

Exit codes: `0` = no violations, `1` = violations found.

### Programmatic API

```python
from python_fp_lint import LintGate, MixedLintGate, ReassignmentGate

# Pure ast-grep (fast, default)
result = LintGate().evaluate(["src/app.py"], project_root=".")

# Semgrep + ast-grep
result = MixedLintGate().evaluate(["src/app.py"], project_root=".")

# Reassignment
result = ReassignmentGate().evaluate(["src/app.py"], project_root=".")

for v in result.violations:
    print(f"[{v.rule}] {v.file}:{v.line} — {v.message}")
```

## Testing

```bash
# Run the full test suite
python -m pytest tests/ -x -q

# Individual test files
python -m pytest tests/test_ast_grep_rules.py -x -q   # 70 tests, ~2.5s
python -m pytest tests/test_lint_gate.py -x -q         # 53 tests, ~19s
python -m pytest tests/test_cli.py -x -q               # 18 tests, ~7s
python -m pytest tests/test_reassignment_gate.py -x -q
python -m pytest tests/test_result.py -x -q
```

## Architecture

```
python_fp_lint/
├── lint_gate.py           # LintGate (pure ast-grep) + MixedLintGate (Semgrep + ast-grep)
├── reassignment_gate.py   # beniget def-use chain analysis
├── result.py              # LintResult, LintViolation dataclasses
├── rules_meta.py          # Rule metadata reader (for CLI rules/schema commands)
├── __init__.py            # Public API exports
├── __main__.py            # CLI entry point (text + JSON output)
├── semgrep-rules.yml      # 26 Semgrep pattern rules (used by MixedLintGate)
├── sgconfig.yml           # ast-grep configuration
└── rules/                 # 28 ast-grep rule files (.yml)
```

Each gate exposes a single method: `evaluate(changed_files, project_root) -> LintResult`. Gates are independent and composable — use one, both, or plug them into a larger pipeline.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `beniget` | Def-use chain analysis (runtime) |
| `pyyaml` | Rule metadata parsing (runtime) |
| `pytest` | Test framework (dev) |
| `sg` (ast-grep) | AST-based lint rules (external tool, required for LintGate) |
| `semgrep` | Pattern-based lint rules (external tool, required for MixedLintGate) |

## License

[MIT](LICENSE.md)
