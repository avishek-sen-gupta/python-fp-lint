# python-fp-lint

[![CI](https://github.com/avishek-sen-gupta/python-fp-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/avishek-sen-gupta/python-fp-lint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE.md)

**python-fp-lint** is a functional-programming linter for Python. It detects mutation, reassignment, and impurity patterns that violate FP discipline, combining three complementary analysis backends:

1. **ast-grep** (27 rules) — tree-sitter AST analysis for FP-specific mutation rules
2. **Ruff** (batteries-included + FP-specific) — Rust-based linter for unused imports, style errors, complexity, and more
3. **beniget** — def-use chain analysis for variable reassignment detection across scopes

The unified `LintGate` runs all three backends in sequence. Each backend that is available contributes violations; missing tools are silently skipped.

## Rules

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

### Ruff rules (batteries-included + FP-specific)

| Ruff code | Category |
|-----------|----------|
| `E` | pycodestyle errors |
| `F` | Pyflakes — unused imports, undefined names, unused vars |
| `W` | pycodestyle warnings |
| `I` | isort — import sorting |
| `B` | flake8-bugbear — mutable defaults, assert False |
| `UP` | pyupgrade — deprecated syntax |
| `SIM` | flake8-simplify — simplifiable constructs |
| `RUF` | Ruff-specific checks |
| `BLE` | Blind except detection |
| `T20` | Print statement detection |
| `TID252` | Relative import detection |
| `C901` | Cyclomatic complexity |

## Setup

### Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — package manager
- [ast-grep](https://ast-grep.github.io/) (`sg`) — required for FP mutation rules
- [Ruff](https://docs.astral.sh/ruff/) — required for hygiene rules

### Install

```bash
uv venv
uv pip install -e ".[dev]"
```

Or install just the library:

```bash
uv pip install -e .
```

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

### JSON output (for LLM agents and toolchains)

```bash
# Lint check with structured output
uv run python -m python_fp_lint --format json check src/

# List all available rules
uv run python -m python_fp_lint --format json rules

# Get JSON schema for output formats
uv run python -m python_fp_lint schema
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
from python_fp_lint import LintGate, LintResult, LintViolation

# Unified gate — runs ast-grep + Ruff + beniget
result = LintGate().evaluate(["src/app.py"], project_root=".")

for v in result.violations:
    print(f"[{v.rule}] {v.file}:{v.line} — {v.message}")
```

## Testing

```bash
# Run the full test suite
uv run pytest tests/ -x -q

# Individual test files
uv run pytest tests/test_ast_grep_rules.py -x -q   # 63 tests
uv run pytest tests/test_lint_gate.py -x -q         # 24 tests
uv run pytest tests/test_cli.py -x -q               # 17 tests
uv run pytest tests/test_reassignment_gate.py -x -q
uv run pytest tests/test_result.py -x -q
```

The test suite includes a self-lint integration test that runs `LintGate` on this repo's own source code and verifies violations are detected.

## CI

GitHub Actions runs on every push to `main` and on pull requests. The pipeline tests on Python 3.13 with:

1. **Black** — formatting check
2. **pytest** — full test suite (132 tests)

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Pre-commit hook

The pre-commit hook runs:

1. **Talisman** — secret detection
2. **Black** — auto-format and re-stage
3. **pytest** — full test suite

All steps use `uv run` for consistent environments.

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

## Design Decisions

### Why Ruff (not Flake8)

Ruff reimplements popular Flake8 plugins (pycodestyle, Pyflakes, bugbear, isort, simplify, and more) in Rust, running **10–100x faster** than Flake8 on real codebases. It ships as a single binary with built-in auto-fix — no plugin installation, no version matrix across six packages. The trade-off is that Ruff does not support custom plugins: you cannot extend it with project-specific rules. That's acceptable here because our FP-specific rules live in ast-grep, which is purpose-built for structural pattern matching.

### Why ast-grep (not hand-written AST visitors)

ast-grep uses tree-sitter to parse Python's concrete syntax tree and match against declarative YAML patterns. A rule like "flag `$LIST.append($ITEM)` inside a `for` loop" is a few lines of YAML; the equivalent `ast.NodeVisitor` in Python would be 50+ lines of imperative traversal code. Declarative rules are easier to review, compose (via `any:`, `all:`, `inside:`), and maintain. ast-grep is also written in Rust, so scanning 27 rules across a codebase adds negligible overhead.

### Why not Semgrep

Semgrep was the original backend for FP mutation rules. It was replaced because:

- **Closed ecosystem.** Semgrep requires login/registration for full functionality and routes rules through their cloud registry. Local-only usage is a second-class path with friction.
- **Performance.** Semgrep's Python-based runner is significantly slower than ast-grep for the same structural matching task.
- **Licensing and direction.** Semgrep's shift toward a commercial platform (Semgrep Cloud, mandatory telemetry in some versions) made it a poor fit for an open-source dev tool that should work offline without accounts.

ast-grep provides the same pattern-matching expressiveness with none of these constraints.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `beniget` | Def-use chain analysis (runtime) |
| `pyyaml` | Rule metadata parsing (runtime) |
| `pytest` | Test framework (dev) |
| `black` | Code formatter (dev) |
| `sg` (ast-grep) | AST-based FP mutation rules (external tool) |
| `ruff` | Hygiene lint rules (external tool) |

## License

[MIT](LICENSE.md)
