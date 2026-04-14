# python-fp-lint

[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE.md)

**python-fp-lint** is a functional-programming linter for Python. It detects mutation, reassignment, and impurity patterns that violate FP discipline, combining three complementary analysis backends:

1. **Semgrep** (26 rules) — fast pattern matching for mutation operations, code smells, and anti-patterns
2. **ast-grep** (2 rules) — tree-sitter AST analysis for complex structural patterns (deep nesting, loop mutation)
3. **beniget** — def-use chain analysis for variable reassignment detection across scopes

When all three backends are present, the linter covers mutation at every level: individual expressions (Semgrep), structural patterns (ast-grep), and dataflow (beniget).

## Rules

### Semgrep rules (26)

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

### ast-grep rules (2)

| Rule | Description |
|------|-------------|
| `no-deep-nesting` | Flags nested `for`/`if` blocks — encourages comprehensions, itertools, or extraction |
| `no-loop-mutation` | Flags 14+ mutation patterns inside `for` loops |

### Reassignment detection (beniget)

Detects variable and parameter reassignment within a single scope using def-use chain analysis. Tracks violations per scope (module, function, class).

## Setup

### Requirements

- Python 3.10+
- [Semgrep](https://semgrep.dev/) — required for `LintGate`
- [ast-grep](https://ast-grep.github.io/) (`sg`) — optional, enables ast-grep rules

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
# Run all checks
python -m python_fp_lint check file1.py file2.py

# Semgrep + ast-grep rules only
python -m python_fp_lint check --semgrep-only file1.py file2.py

# Reassignment checks only
python -m python_fp_lint check --reassignment-only file1.py file2.py
```

### Programmatic API

```python
from python_fp_lint import LintGate, ReassignmentGate

# Semgrep + ast-grep
result = LintGate().evaluate(["src/app.py"], project_root=".")
for v in result.violations:
    print(f"[{v.rule}] {v.file}:{v.line} — {v.message}")

# Reassignment
result = ReassignmentGate().evaluate(["src/app.py"], project_root=".")
for v in result.violations:
    print(f"[{v.rule}] {v.file}:{v.line} — {v.message}")
```

## Testing

```bash
# Run the full test suite
python -m pytest tests/ -x -q

# Run a specific test file
python -m pytest tests/test_lint_gate.py -x -q
python -m pytest tests/test_reassignment_gate.py -x -q
python -m pytest tests/test_cli.py -x -q
python -m pytest tests/test_result.py -x -q
```

Tests are pure unit tests — they do not shell out to Semgrep or ast-grep. Install dev dependencies first: `pip install -e ".[dev]"`.

## Architecture

```
python_fp_lint/
├── lint_gate.py           # Dual Semgrep + ast-grep backend orchestrator
├── reassignment_gate.py   # beniget def-use chain analysis
├── result.py              # LintResult, LintViolation dataclasses
├── __main__.py            # CLI entry point
├── semgrep-rules.yml      # 26 Semgrep pattern rules
├── sgconfig.yml           # ast-grep configuration
└── rules/                 # ast-grep rule files
    ├── no-deep-nesting.yml
    └── no-loop-mutation.yml
```

Each gate exposes a single method: `evaluate(changed_files, project_root) -> LintResult`. Gates are independent and composable — use one, both, or plug them into a larger pipeline.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `beniget` | Def-use chain analysis (runtime) |
| `pytest` | Test framework (dev) |
| `semgrep` | Pattern-based lint rules (external tool) |
| `sg` (ast-grep) | AST-based lint rules (external tool, optional) |

## License

[MIT](LICENSE.md)
