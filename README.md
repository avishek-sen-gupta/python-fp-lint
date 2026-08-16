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
| **Style** | `no-static-method` |
| **Structural** | `no-deep-nesting`, `no-loop-mutation` |
| **Type annotations** | `no-list-dict-param-annotation`, `no-unfrozen-dataclass`, `no-any-type` |

`no-any-type` bans *explicit* `typing.Any` usage only (`x: Any`, `-> Any`, `dict[str, Any]`, ...).
It cannot see *implicit* Any from missing annotations (e.g. `def f(x):`) — pyright's
`reportUnknownParameterType`/`reportMissingParameterType`/`reportUnknownVariableType` cover that
complementary case and are not duplicated here.

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
| `BLE` | Blind except detection — catches `except Exception:`/`except BaseException:`; replaces the old `no-except-exception` ast-grep rule |
| `T20` | Print statement detection |
| `TID252` | Relative import detection |
| `C901` | Cyclomatic complexity |
| `ANN401` | Explicit `Any` in function parameter and return annotations — partial overlap with `no-any-type`, which also covers variable annotations and `Any` nested in generics |

## Setup

### Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — package manager (for development)

[ast-grep](https://ast-grep.github.io/) and [Ruff](https://docs.astral.sh/ruff/) are declared as
dependencies and ship as wheels, so installing the package installs both binaries. No separate
`brew install` step is required.

### Install

Standalone, no clone needed (installs straight from git — the package is not on PyPI yet):

```bash
# One-off run
uvx --from git+https://github.com/avishek-sen-gupta/python-fp-lint python-fp-lint check --config fp.json src/

# Or install the `python-fp-lint` command permanently
uv tool install git+https://github.com/avishek-sen-gupta/python-fp-lint
pipx install git+https://github.com/avishek-sen-gupta/python-fp-lint
```

For development:

```bash
uv sync --extra dev
```

## Usage

### CLI

The package installs a `python-fp-lint` console script; `python -m python_fp_lint` is equivalent
and works without the entry point.

```bash
# Run all checks on files
python-fp-lint check --config fp.json file1.py file2.py
uv run python -m python_fp_lint check --config fp.json file1.py file2.py

# Directories (recursive) and globs
uv run python -m python_fp_lint check --config fp.json src/
uv run python -m python_fp_lint check --config fp.json 'src/**/*.py'
uv run python -m python_fp_lint check --config fp.json src/ tests/test_foo.py 'lib/*.py'
```

### Configuring rules

`check` and `precommit` **require** `--config PATH`. There is no search and no default location:
the config file is the one you name, or the command is a usage error. Copy
[`config.example.json`](config.example.json) as a starting point.

Rules can be configured via CLI flags, the config file, or the Python API. Resolution order:
CLI/constructor > config file > built-in defaults.

**CLI flags:**

```bash
# Only run specific Ruff rule groups
uv run python -m python_fp_lint check --config fp.json --ruff-select "E,F,W" src/

# Only enable specific ast-grep rules
uv run python -m python_fp_lint check --config fp.json --ast-grep-rules "no-list-append,no-dict-update" src/
```

**Config file** (any path you like — you name it with `--config`; see `config.example.json`):

```json
{
  "ruff_select": "E,F,W,I,B,UP,SIM,RUF,BLE,T20,TID252,C901",
  "ast_grep_rules": ["no-list-append", "no-dict-update"]
}
```

**Python API:**

```python
gate = LintGate(ruff_select="E,F", ast_grep_rules=["no-list-append"])
```

Omitting a key (or passing `None`) uses all available rules for that backend.

### JSON output (for LLM agents and toolchains)

```bash
# Lint check with structured output
uv run python -m python_fp_lint --format json check --config fp.json src/

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

## Claude Code lint gate

A PreToolUse hook blocks `Edit` and `Write` tool calls that would introduce new FP violations. Pre-existing violations are ignored — only regressions are blocked (Option B diff).

### Install

Run from the root of the project you want to protect (must have a `.claude/` directory):

```bash
# From the python-fp-lint repo
./install-lint.sh
```

This copies the hook to `~/.claude/plugins/python-fp-lint/` and wires `Edit` and `Write` matchers into `.claude/settings.json`.

Requires: `jq`, `python-fp-lint` reachable via `uv run python -m python_fp_lint`.

### Usage

```bash
/lint on      # enable gate for this project
/lint off     # disable gate
/lint status  # check state
/lint         # toggle
```

The gate is **off by default**. Lock file: `/tmp/ctx-lint/<md5-of-pwd>`.

Config is optional for this gate — it has to work the moment the hook is installed, so with no
config it uses built-in defaults. Set `PYTHON_FP_LINT_CONFIG=/path/to/fp.json` to point it at one.

When a violation is introduced, the tool call is blocked with a message listing the new violations. Fix them or disable the gate with `/lint off`.

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
2. **pytest** — full test suite (210 tests)

See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Pre-commit gate

The `precommit` subcommand is a commit gate for **your** project. It lints the **staged blob**
(`git show :path`), not the worktree file — those differ whenever a file is partially staged, and
it is the blob that gets committed.

Every violation in a staged file blocks the commit, including ones that predate the change being
committed. Files you didn't stage are not examined.

```bash
python-fp-lint precommit --config fp.json            # gate the staged files
python-fp-lint precommit --config fp.json --strict   # fail if ast-grep/Ruff are missing
python-fp-lint precommit --config fp.json src/app.py # narrow to a subset of the staged files
```

Exit codes: `0` = clean, `1` = violations, `2` = a required backend is missing (`--strict`).

`--strict` matters for a gate. By default a missing `sg` or `ruff` is silently skipped, which
turns a broken install into a silently passing commit.

### Installer script

From the root of the project you want to gate:

```bash
/path/to/python-fp-lint/install-precommit.sh
```

It copies the 27 ast-grep rule files into `.python-fp-lint/` at the repo root, seeds `fp.json`
from `config.example.json` with `lint_rules_dir` pointing there, wires the hook into
`.pre-commit-config.yaml`, and runs `pre-commit install`. Re-running refreshes the rules and
leaves everything else alone.

**Never place a `.gitignore` inside `.python-fp-lint/`.** ast-grep silently matches nothing when
an ignore file inside the rules directory excludes them — the gate then passes everything while
reporting success. This is why the rules are copied out of the installed package at all: the
package normally lands in `.venv`, whose self-ignoring `.gitignore` triggers exactly that.
Listing `.python-fp-lint/` in the repo's *root* `.gitignore` tests fine, but committing the
directory is safer, since CI needs it too.

It pins `rev: main`, which is a mutable reference — pre-commit clones it once and never updates
it. Once this repo has tags, change `rev` in `.pre-commit-config.yaml` or run
`pre-commit autoupdate`. The script says so on completion.

An existing `.pre-commit-config.yaml` is edited textually rather than round-tripped through
a YAML parser, so your comments and key order survive.

### Via the pre-commit framework

To wire it by hand instead, add to your project's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/avishek-sen-gupta/python-fp-lint
    rev: main   # pin to a tag or SHA
    hooks:
      - id: python-fp-lint
        args: [--config, fp.json]   # required
```

pre-commit builds an isolated environment from this repo, so ast-grep and Ruff come along
automatically.

### Via a plain git hook

No framework needed — `.git/hooks/pre-commit`:

```sh
#!/bin/sh
exec python-fp-lint precommit --strict --config fp.json
```

```bash
chmod +x .git/hooks/pre-commit
```

### This repo's own pre-commit hook

For contributors to python-fp-lint itself, the local hook runs Talisman (secret detection), Black
(auto-format and re-stage), and the full pytest suite — all via `uv run`.

## Architecture

```
python_fp_lint/
├── lint_gate.py           # Unified LintGate (ast-grep + Ruff + beniget)
├── reassignment_gate.py   # beniget def-use chain analysis (called by LintGate)
├── result.py              # LintResult, LintViolation dataclasses
├── rules_meta.py          # Rule metadata reader (for CLI rules/schema commands)
├── precommit.py           # Staged-blob linting for the git commit gate
├── __init__.py            # Public API: LintGate, LintResult, LintViolation
├── __main__.py            # CLI entry point (text + JSON output)
├── sgconfig.yml           # ast-grep configuration
└── rules/                 # 27 ast-grep rule files (.yml)

hooks/
├── lint-check.sh          # Claude Code PreToolUse hook (Edit + Write)
└── lib/hash.sh            # Portable MD5 helper for lock file paths

bin/
└── lint                   # on/off/status/toggle CLI

commands/
└── lint.md                # /lint slash command for Claude Code

install-lint.sh            # Wires hook into a project's .claude/settings.json
install-precommit.sh       # Wires hook into a project's .pre-commit-config.yaml
.pre-commit-hooks.yaml     # Hook manifest for the pre-commit framework
```

Each backend is called in sequence: ast-grep, Ruff, beniget. Missing tools are silently skipped —
pass `--strict` to fail loudly instead.

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
| `ast-grep-cli` | AST-based FP mutation rules — ships the `sg`/`ast-grep` binaries (runtime) |
| `ruff` | Hygiene lint rules — ships the `ruff` binary (runtime) |
| `pytest` | Test framework (dev) |
| `black` | Code formatter (dev) |

An `sg`/`ruff` already on `PATH` takes precedence over the bundled wheels.

## License

[MIT](LICENSE.md)
