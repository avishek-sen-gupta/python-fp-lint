# python-fp-lint

[![CI](https://github.com/avishek-sen-gupta/python-fp-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/avishek-sen-gupta/python-fp-lint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE.md)

**python-fp-lint** is a functional-programming linter for Python. It detects mutation, reassignment, and impurity patterns that violate FP discipline, combining three complementary analysis backends:

1. **ast-grep** (36 rules) — tree-sitter AST analysis for FP-specific mutation rules
2. **Ruff** (batteries-included + FP-specific) — Rust-based linter for unused imports, style errors, complexity, and more
3. **beniget** — def-use chain analysis for variable reassignment detection across scopes

The unified `LintGate` runs all three backends in sequence. By default a missing `sg` or `ruff` is skipped without error; pass `--strict` (as the pre-commit hooks do) to fail instead.

## Rules

### At a glance

Every check, grouped by what it is for. Each violation is reported as
`[rule] file:line — message`, where `rule` is one of the IDs listed here.

| Kind of lint | What it catches | Rules |
|---|---|---|
| **In-place mutation of collections** | Calling a mutating method on a list, dict or set, or writing/deleting through a subscript | [List, dict, set and subscript rules](#ast-grep-rules-36) (`no-list-*`, `no-dict-*`, `no-set-*`, `no-subscript-*`, `no-setitem-call`) |
| **Mutation of names and objects** | `+=`-style updates, mutation inside loops, attributes assigned after construction | `no-local-augmented-mutation`, `no-attribute-augmented-mutation`, `no-loop-mutation`, `no-mutation-outside-init` |
| **Reassignment** | Binding the same name twice in one scope, parameters included | [`reassignment`](#reassignment-beniget) (beniget) |
| **None and Optional** | Using `None` to model absence: `is None` checks, `Optional[...]`, `None` defaults, `None` match cases, `or None` | `no-is-none`, `no-is-not-none`, `no-optional-none`, `no-none-default-param`, `no-none-case-pattern`, `no-or-none-fallback` |
| **Types** | Escape-hatch types (`Any`, `object`), mutable dataclasses, concrete `list`/`dict` parameter types, `StrEnum` | `no-any-type`, `ANN401`, `no-object-type`, `no-unfrozen-dataclass`, `no-list-dict-param-annotation`, `no-str-enum` |
| **Function size and shape** | Too many branches, too many statements, too many positional parameters, nested `for`/`if` | `C901` (≤ 3), `PLR0915` (≤ 15), `PLR0917` (≤ 4), `no-deep-nesting` |
| **Code organisation** | `@staticmethod` and `@classmethod`, which belong at module level or as instance behaviour | `no-static-method`, `no-classmethod-utility` |
| **Test quality** | Tests that check nothing, assertions that cannot fail usefully, `xfail` with no stated reason | `no-assertionless-test`, `no-weak-assert`, `no-xfail-without-reason` |
| **General hygiene** | Style errors, unused/undefined names, import order and relative imports, common bugs, outdated syntax, blind `except`, `print` | Ruff `E`, `W`, `F`, `I`, `TID252`, `B`, `UP`, `SIM`, `RUF`, `BLE`, `T20` |

Two further gates are installed separately and are not part of `LintGate`: a
[Pyright gate](#pyright-gate) for strict type checking and a [Black hook](#black-hook) for
formatting.

### ast-grep rules (36)

| Category | Rule | Flags | Write instead |
|----------|------|-------|---------------|
| **List mutation** | `no-list-append` | `xs.append(x)` | concatenation or a comprehension |
| | `no-list-extend` | `xs.extend(ys)` | `xs + ys` |
| | `no-list-insert` | `xs.insert(i, x)` | slicing + concatenation |
| | `no-list-pop` | `xs.pop()` | slicing |
| | `no-list-remove` | `xs.remove(x)` | a filtering comprehension |
| **Dict mutation** | `no-dict-clear` | `d.clear()` | bind a new empty dict |
| | `no-dict-update` | `d.update(other)` | `{**d, **other}` |
| | `no-dict-setdefault` | `d.setdefault(k, v)` | an explicit conditional, or a `defaultdict` at construction |
| **Set mutation** | `no-set-add` | `s.add(x)` | `s \| {x}` |
| | `no-set-discard` | `s.discard(x)` | `s - {x}` |
| **Subscript mutation** | `no-subscript-mutation` | `xs[i] = v`, `d[k] = v` | comprehensions or immutable update patterns |
| | `no-subscript-del` | `del d[k]` | comprehensions or immutable update patterns |
| | `no-subscript-augmented-mutation` | `d[k] += 1` | immutable update patterns |
| | `no-subscript-tuple-mutation` | `a[i], a[j] = ...` | immutable update patterns |
| | `no-setitem-call` | `d.__setitem__(k, v)`, `operator.setitem(...)` | comprehensions or immutable update patterns |
| **Augmented assignment** | `no-local-augmented-mutation` | `total += x` on a local | a new binding, or `sum`/`reduce` |
| | `no-attribute-augmented-mutation` | `self.count += 1` | return a new object |
| **None / Optional** | `no-is-none` | `x is None` | `match`, or an Option type |
| | `no-is-not-none` | `x is not None` | `match`, or an Option type |
| | `no-optional-none` | `Optional[T]`, `T \| None` | sentinel values or separate code paths |
| | `no-none-default-param` | `def f(x=None)` | an immutable empty default (`()`, `frozenset()`) or a sentinel — not `[]`/`{}`, which Ruff's `B006` flags |
| | `no-or-none-fallback` | `value or None` | pass the value through unchanged |
| | `no-none-case-pattern` | `case None:` | a sentinel case or an Option type |
| **Style** | `no-static-method` | `@staticmethod` | a module-level function |
| | `no-classmethod-utility` | any `@classmethod` | a module-level function or instance behaviour |
| **Structural** | `no-deep-nesting` | a `for` or `if` nested inside another `for` or `if` | comprehensions, `itertools`, or a helper function |
| | `no-loop-mutation` | a mutating call, subscript write or `+=` inside a `for` body | comprehensions, `reduce` |
| | `no-mutation-outside-init` | `self.x = ...` outside `__init__` | construct complete objects; never mutate them |
| **Type annotations** | `no-list-dict-param-annotation` | `list`/`dict` as a parameter type | `Sequence`/`Mapping` from `collections.abc` |
| | `no-unfrozen-dataclass` | `@dataclass` without `frozen=True` | `@dataclass(frozen=True)` |
| | `no-any-type` | explicit `Any`, anywhere in an annotation | a precise type, `Protocol`, `TypeVar` or union |
| | `no-object-type` | `object` used as a type | a precise type, `Protocol` or union |
| | `no-str-enum` | `StrEnum`, `class E(str, Enum)` | a plain `Enum`, converted at the boundary |
| **Test quality** | `no-assertionless-test` | a `test_*` function with no `assert`, `pytest.raises`/`warns`/`fail`, or `.assert*()` call | assert a concrete outcome, or `pytest.raises` for an expected error |
| | `no-weak-assert` | asserting existence, containment or truthiness | assert a concrete expected value |
| | `no-xfail-without-reason` | `@pytest.mark.xfail` with no `reason=` | state why, and reference an issue |

`no-any-type` bans *explicit* `typing.Any` usage only (`x: Any`, `-> Any`, `dict[str, Any]`, ...).
It cannot see *implicit* Any from missing annotations (e.g. `def f(x):`) — pyright's
`reportUnknownParameterType`/`reportMissingParameterType`/`reportUnknownVariableType` cover that
complementary case and are not duplicated here. `no-object-type` covers the same ground for
`object`, the other untyped-blob escape hatch.

`no-weak-assert` and `no-assertionless-test` split the job of the older `test-vacuous` rule,
kept in `disabled-rules/`. That rule flagged any test without an `==`/`<`-style comparison,
which made it fire on 254 of this repo's own 520 tests: `not in` checks, `is True`, and
`pytest.raises` tests all tripped it. Now `no-weak-assert` judges each assertion on its own,
and `no-assertionless-test` catches only the case it cannot see, a test with no check at
all. A test whose assertions live in a helper it calls is flagged too; name the helper's
outcome in the test, or have the helper return a value the test asserts on.

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
| `C901` | Cyclomatic complexity — ceiling configurable via `max_complexity`, default **3** (see [Cyclomatic complexity](#cyclomatic-complexity)) |
| `PLR0915` | Statement count per function — ceiling configurable via `max_statements`, default **15** (see [Statement count](#statement-count)) |
| `PLR0917` | Positional parameters per function — ceiling configurable via `max_positional_args`, default **4** (see [Positional parameters](#positional-parameters)) |
| `ANN401` | Explicit `Any` in function parameter and return annotations — partial overlap with `no-any-type`, which also covers variable annotations and `Any` nested in generics |

### Reassignment (beniget)

Reported as rule `reassignment`. Using beniget's def-use chains, it flags every binding of
a name after the first within a single scope (module, function, class or comprehension), parameters included:

```
[reassignment] src/handler.py:12 — 'result' reassigned (scope: FunctionDef)
```

Redefined functions and classes, and repeated imports, are not counted. A name rebound in
a *nested* scope is a new variable, not a reassignment. This check has no config switch:
it always runs.

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

# The whole repo, tracked or not, committed or not
python-fp-lint check --config fp.json .
```

Inside a git repo, a directory argument expands to every file git doesn't ignore: tracked files
plus untracked ones, minus anything matched by `.gitignore`, `.git/info/exclude`, or your global
excludes. So `check .` skips `.venv/`, `build/`, and the like without any `exclude` config.
Outside a git repo, a directory is walked in full. What you name explicitly is always linted:
a file, a glob, or a directory that is itself ignored (`check .venv/` walks all of it).

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

# Raise or lower the cyclomatic complexity ceiling
uv run python -m python_fp_lint check --config fp.json --max-complexity 5 src/

# Raise or lower the per-function statement ceiling
uv run python -m python_fp_lint check --config fp.json --max-statements 20 src/

# Raise or lower the per-function positional-parameter ceiling
uv run python -m python_fp_lint check --config fp.json --max-positional-args 6 src/
```

**Config file** (any path you like — you name it with `--config`; see `config.example.json`):

```json
{
  "ruff_select": "E,F,W,I,B,UP,SIM,RUF,BLE,T20,TID252,C901,PLR0915,PLR0917,ANN401",
  "max_complexity": 3,
  "max_statements": 15,
  "max_positional_args": 4,
  "ast_grep_rules": ["no-list-append", "no-dict-update"],
  "exclude": ["generated/", "**/migrations/**", "*_pb2.py"]
}
```

**Python API:**

```python
from python_fp_lint import LintGate, LintSettings, load_settings

# What a config file asks for:
gate = LintGate(settings=load_settings("fp.json"))

# Or settings built directly; unspecified fields take the built-in defaults:
gate = LintGate(
    settings=LintSettings(
        ruff_select="E,F",
        ast_grep_rules=["no-list-append"],
        exclude=["generated/"],
        max_complexity=5,
        max_statements=20,
        max_positional_args=6,
    )
)
```

`LintGate` takes one frozen dataclass, `LintSettings`, by keyword, and never reads a file
itself: every field holds a resolved value. To combine a config file with overrides the way
the CLI does, build the two layers and resolve them -- the overriding layer wins field by
field, then the config file, then the default:

```python
from python_fp_lint.settings import ConfigLayer, layer_from_config_file, resolve_settings

settings = resolve_settings(
    ConfigLayer(max_statements=20),           # overrides, as the CLI flags would give
    layer_from_config_file("fp.json"),        # the config file
    project_root=".",
)
```

In a layer, a setting no source supplied is `UNSET`; a resolved `LintSettings` never contains
it. Config errors -- a missing file, malformed JSON, a negative ceiling -- surface while
resolving, before any linting.

Omitting a key uses the built-in default: for Ruff, the codes listed under
[Ruff rules](#ruff-rules-batteries-included--fp-specific); for ast-grep, every rule file in the rules
directory; for the ceilings, the defaults stated in their sections below.

For the two list settings, `ast_grep_rules` and `exclude`, an empty list is the same as
omitting them, at every level: `LintSettings(exclude=())`, `"exclude": []` in the config and
an absent `--exclude` all mean "none given here", so the next source applies. In particular an
empty `ast_grep_rules` is no filter at all, and every rule runs.

| Key | Meaning |
|---|---|
| `"baseline"` | path to the ratchet baseline file; unset disables the ratchet — see [Violation ratchet](#violation-ratchet) |

### Cyclomatic complexity

`max_complexity` caps the cyclomatic complexity of any single function. A function
over the cap is reported as Ruff's `C901`:

```
[C901] src/handler.py:42 — `dispatch` is too complex (7 > 3)
```

The default is **3** — deliberately stricter than Ruff's own default of 10, on the
view that a function past three branches wants decomposing. Set it wherever you
like:

```jsonc
{ "max_complexity": 5 }   // or --max-complexity 5, or LintSettings(max_complexity=5)
```

`0` fails every function and is accepted (it is occasionally useful for surveying
complexity across a codebase); a negative or non-integer value is a config error.

Two things worth knowing:

- **The metric is Ruff's approximation of McCabe.** "McCabe complexity" and
  "cyclomatic complexity" are the same measure, but Ruff computes it by walking the
  AST and counting branching statements — `if`/`elif`/`else`, loops, `except`
  handlers, `with`, `match` arms, nested definitions. It does **not** count boolean
  `and`/`or` operators or ternaries as decision points, where `radon` and some other
  tools do. Ruff's number therefore runs slightly lower than radon's on the same
  function.
- **`C901` must stay in `ruff_select`.** It is the rule that reports this, so if you
  override `ruff_select` and leave `C901` out, `max_complexity` silently stops
  applying. The built-in default includes it.

The setting is passed to Ruff as an inline `--config` override, which beats any
`pyproject.toml` in the project being scanned — the gate's ceiling is the one that
applies.

### Statement count

`max_statements` caps how many **statements** a single function may contain. This is a
count of statements, not of physical editor lines: blank lines, comments and a single
expression wrapped over five lines all count as one statement or none, while several
statements crammed onto one line with semicolons each count separately. A function over
the cap is reported as Ruff's `PLR0915`:

```
[PLR0915] src/handler.py:42 — Too many statements (18 > 15)
```

The default is **15** — far stricter than Ruff's own default of 50, on the same view that
drives `max_complexity`: a long method wants decomposing. It is not 10, because a strict
cap turns logging and other straight-line boilerplate into refactoring busywork;
`max_complexity` already catches the branching that makes a function hard to read. Set it
wherever you like:

```jsonc
{ "max_statements": 20 }   // or --max-statements 20, or LintSettings(max_statements=20)
```

`0` fails every function that has a body and is accepted; a negative or non-integer value
is a config error.

Two things worth knowing:

- **The trailing `return` is not counted.** Ruff follows pylint here, so a function
  ending in `return x` scores one statement lower than a naive count suggests.
- **`PLR0915` must stay in `ruff_select`.** It is the rule that reports this, so if you
  override `ruff_select` and leave `PLR0915` out, `max_statements` silently stops
  applying. The built-in default includes it.

Like `max_complexity`, the setting is passed to Ruff as an inline `--config` override, so
it beats any `pyproject.toml` in the project being scanned.

### Positional parameters

`max_positional_args` caps how many **positional** parameters a single function may
declare. Keyword-only parameters (those after a bare `*`), `*args`, `**kwargs` and a
method's `self`/`cls` are not counted; positional-only parameters (before a `/`) are. A
function over the cap is reported as Ruff's `PLR0917`:

```
[PLR0917] src/handler.py:42 — Too many positional arguments (6 > 4)
```

The default is **4** — deliberately stricter than Ruff's own default of 5. The usual fix
is not to bundle the parameters into a mutable bag but to make the trailing ones
keyword-only, so call sites name them, or to group related ones into a frozen dataclass.
Set the ceiling wherever you like:

```jsonc
{ "max_positional_args": 6 }   // or --max-positional-args 6, or LintSettings(max_positional_args=6)
```

`0` fails every function that takes a positional parameter and is accepted; a negative or
non-integer value is a config error.

Two things worth knowing:

- **It needs Ruff 0.16 or later.** Earlier releases ship `PLR0917` as a preview rule, and
  selecting it without `--preview` is silently a no-op. The package depends on
  `ruff>=0.16`, but a different `ruff` earlier on `PATH` is the one that runs.
- **`PLR0917` must stay in `ruff_select`.** If you override `ruff_select` and leave it
  out, `max_positional_args` silently stops applying. The built-in default includes it.

The total parameter count (Ruff's `PLR0913`, `max-args`) is not gated.

### Excluding files

`exclude` is a list of globs; a file matching any of them is never linted, by any
backend. It applies to `check`, `precommit` (matched against the staged, repo-relative
path) and the Claude Code `hook-check` gate alike.

```json
{
  "exclude": ["generated/", "**/migrations/**", "*_pb2.py", "tests/fixtures/*.py"]
}
```

Matching rules:

| Pattern | Matches |
|---|---|
| `*_pb2.py` | a pattern with no `/` is matched against the **basename**, at any depth |
| `generated/` | a trailing `/` excludes everything under that directory |
| `src/*.py` | `*` and `?` stop at a path separator — not `src/deep/a.py` |
| `**/migrations/**` | `**` crosses separators |

Paths are matched relative to the project root (the directory `check` runs in, or the
repo root for `precommit`). `--exclude` takes a comma-separated list and overrides the
config file:

```bash
uv run python -m python_fp_lint check --config fp.json --exclude "generated/,*_pb2.py" src/
```

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

# Unified gate, all defaults; see "Configuring rules" for LintSettings and load_settings
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
./install-claude-hook.sh
```

This copies the hook to `~/.claude/plugins/python-fp-lint/` and wires `Edit` and `Write` matchers into `.claude/settings.json`.

Requires: `jq`, `python-fp-lint` reachable via `uv run python -m python_fp_lint`.

To remove it, run `./uninstall-claude-hook.sh` from the same project root.

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
uv run pytest tests/test_ast_grep_rules.py -x -q
```

| Area | Test files |
|---|---|
| Rules | `test_ast_grep_rules.py`, `test_ruff_integration.py`, `test_reassignment_gate.py`, `test_rule_inventory.py` |
| Ceilings | `test_max_complexity.py`, `test_max_statements.py`, `test_max_positional_args.py` |
| Gate and config | `test_lint_gate.py`, `test_backends.py`, `test_config.py`, `test_exclude.py`, `test_result.py` |
| Entry points | `test_cli.py`, `test_precommit.py`, `test_hook_check.py` |
| Ratchet | `test_ratchet.py`, `test_baseline.py` |
| Installers | `test_precommit_lint_installer.py`, `test_precommit_pyright_installer.py`, `test_precommit_black_installer.py` |
| Test harness | `test_fixture_isolation.py` |

`test_rule_inventory.py` guards the places this README, `config.example.json` and the `rules`
command restate the rule list, so a rule added in one place and not the others fails the build.

The test suite includes a self-lint integration test that runs `LintGate` on this repo's own source code and verifies violations are detected.

## CI

GitHub Actions runs on every push to `main` and on pull requests. The pipeline tests on Python 3.13 with:

1. **Black** — formatting check
2. **pytest** — full test suite

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
/path/to/python-fp-lint/install-precommit-lint.sh
```

It copies the ast-grep rules into `.python-fp-lint/` at the repo root, seeds `fp.json`
from `config.example.json` with `lint_rules_dir` pointing there, wires the commit gate and the
on-demand [`python-fp-lint-check`](#linting-without-committing) hook into
`.pre-commit-config.yaml`, and runs `pre-commit install`. Re-running refreshes the rules, adds
the check hook if it is missing, and leaves everything else alone.

**Activating the git hook can fail without the wiring failing, and all three installers say so
rather than stopping.** The commonest cause is `core.hooksPath`: pre-commit refuses to install
while it is set, so you get a wired config and no git hook. The installer warns, names the path,
prints the two commands that finish the job, and exits 0 — it does **not** unset `core.hooksPath`
for you. That setting is yours, it may be there because another tool wants it (talisman is one),
and dropping it is your call. The wiring is still worth having on its own: `pre-commit run` in CI
needs no git hook at all.

**Never place a `.gitignore` inside `.python-fp-lint/`.** ast-grep silently matches nothing when
an ignore file inside the rules directory excludes them — the gate then passes everything while
reporting success. This is why the rules are copied out of the installed package at all: the
package normally lands in `.venv`, whose self-ignoring `.gitignore` triggers exactly that.
Listing `.python-fp-lint/` in the repo's *root* `.gitignore` tests fine, but committing the
directory is safer, since CI needs it too.

It tracks `main`. pre-commit never re-fetches a branch name (`rev: main` is cloned once, then
frozen, and warned about on every run), so the script instead runs
`pre-commit autoupdate --bleeding-edge` to pin `rev` to the SHA at the tip of `main`. To move to
the latest `main` later, re-run the script or:

```bash
pre-commit autoupdate --bleeding-edge --repo https://github.com/avishek-sen-gupta/python-fp-lint
```

Scope it with `--repo` as shown: a bare `--bleeding-edge` moves *every* repo in your config to
its default branch. If the update fails (offline, say), the script warns, leaves `rev: main`,
and carries on.

An existing `.pre-commit-config.yaml` is edited textually rather than round-tripped through
a YAML parser, so your comments and key order survive.

To undo it, from the same project root:

```bash
/path/to/python-fp-lint/uninstall-precommit-lint.sh
```

It removes the python-fp-lint block from `.pre-commit-config.yaml` (deleting the file if
nothing else is left in it) and deletes `.python-fp-lint/`. `fp.json` is deleted only if it
is still exactly what the installer seeded; otherwise it is kept and `lint_rules_dir` is
reset to `null`. A `lint_rules_dir` the installer overwrote in a pre-existing `fp.json` is
not restored. It does not run `pre-commit uninstall`, because that git hook runs every hook
in the config, not only this one. If python-fp-lint was your only hook, run it yourself.

### Via the pre-commit framework

To wire it by hand instead, add to your project's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/avishek-sen-gupta/python-fp-lint
    rev: main   # pin to a tag or SHA
    hooks:
      - id: python-fp-lint
        args: [--config, fp.json]   # required
      - id: python-fp-lint-check    # optional: on-demand, never runs at commit
        args: [--config, fp.json]
```

The `python-fp-lint` hook declares `stages: [pre-commit]`, so it runs once per commit even when
the repo also installs a `commit-msg` hook. Every hook these installers write carries it too --
Black and Pyright get it from the installer, since their own manifests declare no stage.

Your own hooks don't get that for free: pre-commit runs a hook with no `stages:` at *every*
installed stage, so with a `commit-msg` hook installed, each of them runs twice per commit
(`always_run` hooks in full, the rest as "no files to check" noise). Set this at the top of
`.pre-commit-config.yaml` to stop that:

```yaml
default_stages: [pre-commit]
```

### Linting without committing

The commit gate only ever sees staged blobs. To lint the working tree on demand, the installer
also wires `python-fp-lint-check`, which runs `python-fp-lint check` at pre-commit's `manual`
stage, so a commit never triggers it:

```bash
pre-commit run python-fp-lint-check --hook-stage manual --all-files        # every tracked file
pre-commit run python-fp-lint-check --hook-stage manual --files src/app.py # specific files
```

`--all-files` means files git knows about. A brand-new file you haven't `git add`ed is skipped,
so name it with `--files`. Re-running `install-precommit-lint.sh` adds this hook to a project wired
before it existed.

To lint the entire repo regardless of git state (tracked, untracked, staged or not), skip
pre-commit and point `check` at the root. Directory walks honour `.gitignore`, so this covers
your code and not your virtualenv:

```bash
python-fp-lint check --config fp.json .
# or, with nothing installed:
uvx --from git+https://github.com/avishek-sen-gupta/python-fp-lint python-fp-lint check --config fp.json .
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

For contributors to python-fp-lint itself, the local hook runs Talisman (secret detection),
the terminology guards, and this repo's own lint gate; the test suite runs in CI rather than at
commit.

The repo is held to its own rules through the [violation ratchet](#violation-ratchet).
`fp.json` sets only `baseline`, so every other setting is the gate's built-in default and the
repo is always judged by the current ruleset. `fp-baseline.json` holds the recorded total. The
hook runs the working copy's gate (`uv run python -m python_fp_lint`), not a pinned release, so
a rule change applies to this repo the moment it is made. CI runs the same check with
`--no-tighten`. A commit that adds a violation is blocked; one that removes violations lowers
the baseline, stages it and fails once, so re-run the commit. After changing a rule or a
default ceiling, re-run `uv run python -m python_fp_lint baseline update --config fp.json`
and commit the new total with the change. Every hook in it
declares its `stages:` explicitly, because one of them is a `commit-msg` hook -- which is
exactly the condition that makes an omitted `stages:` double-run.

If you add a hook that runs `pytest` here, note that the suite is written to survive it: git
exports `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE` to its hooks, those override a
subprocess `cwd=`, and the tests both create repos and stage files. `tests/conftest.py` strips
them for the session and `tests/gitenv.py` explains why. Production code is deliberately left
reading them -- that is how the gate sees the staged index.

## Pyright gate

Separate from everything above, and optional. `python-fp-lint`'s `no-any-type` rule bans
*explicit* `Any`; it cannot see the *implicit* `Any` that flows from a missing annotation.
Pyright's `reportUnknownParameterType` / `reportMissingParameterType` /
`reportUnknownVariableType` cover exactly that complementary case, so a second installer wires
Pyright in as its own pre-commit hook.

From the root of the project you want to gate:

```bash
/path/to/python-fp-lint/install-precommit-pyright.sh
```

It writes a `pyrightconfig.json` at the repo root and adds one hook to
`.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/RobertCraigie/pyright-python
  rev: v1.1.414
  hooks:
    - id: pyright
      stages: [pre-commit]
```

The hook runs at the commit stage, and only there: **it blocks.** `stages:` is explicit
rather than left to pre-commit's default, because a hook that omits it runs at *every*
installed stage -- so alongside a `commit-msg` hook, Pyright would type-check twice per
commit. The `rev` is pinned to a real tag so the wiring works offline, then
`pre-commit autoupdate --repo <url>` moves it to the latest release. No `--bleeding-edge`
here, unlike the lint installer -- that one tracks this project's `main`, while
pyright-python ships tags.

The seeded config is deliberately small:

```json
{
  "typeCheckingMode": "strict",
  "venvPath": ".",
  "venv": ".venv"
}
```

- **No `include`.** Pyright scans the whole repo, which keeps the file layout-agnostic; its
  own defaults already skip `node_modules`, `__pycache__` and dotted directories.
- **No `pythonVersion`.** This project's floor is 3.10, but that is not necessarily yours,
  and pinning ours would flag your valid code. Add it yourself if you want the editor to
  catch syntax newer than you support.
- **`venvPath`/`venv`** is the setting that earns its keep: without it, everyone who opens
  the repo sees phantom unresolved-import errors for your dependencies. Point it elsewhere if
  your environment is not `.venv`. A missing path is a warning, not an error, so a fresh
  clone is never blocked by it.

### Strict is strict

There is **no ratchet for Pyright**. Its findings are not part of python-fp-lint's violation
total, so a codebase that has never been type-checked cannot commit until strict passes. On
this repo, strict reports 285 errors against 4 in basic mode -- almost all of them the
`reportUnknown*` family, which is the honest size of the implicit-`Any` problem.

If that is too much to swallow at once, edit `pyrightconfig.json` after installing: set
`typeCheckingMode` to `"standard"` or `"basic"`, or turn individual rules down to
`"warning"`, and tighten as you go.

To undo it, from the same project root:

```bash
/path/to/python-fp-lint/uninstall-precommit-pyright.sh
```

It removes the Pyright block from `.pre-commit-config.yaml` (deleting the file if nothing
else is left in it) and removes `pyrightconfig.json` **only if it is still exactly what the
installer seeded** -- any edit of your own and it is kept. Like the lint uninstaller, it does
not run `pre-commit uninstall`, because that git hook runs every hook in the config.

## Black hook

A third installer, for the formatter. There is nothing clever here -- it wires the standard
`psf/black` hook -- but it saves hand-editing `.pre-commit-config.yaml`, and it uninstalls
cleanly:

```bash
/path/to/python-fp-lint/install-precommit-black.sh
/path/to/python-fp-lint/uninstall-precommit-black.sh
```

```yaml
- repo: https://github.com/psf/black
  rev: 26.5.1
  hooks:
    - id: black
      stages: [pre-commit]
```

`stages:` is explicit for the same reason it is on the Pyright hook: without it Black would
reformat the same staged files a second time in any repo that also installs a `commit-msg`
hook.

Two things set it apart from the other two gates.

**No config file is seeded.** Black's premise is not having settings. If you want
`line-length` or `target-version`, they belong in your own `pyproject.toml` under
`[tool.black]` -- not in something an installer wrote and an uninstaller would have to reason
about deleting. The uninstaller therefore removes the hook and nothing else; your
`pyproject.toml` is never touched, and your files stay formatted, which is the point of
having run it.

**This hook rewrites your files.** The lint and Pyright gates report; Black edits. pre-commit
treats a hook that modified the worktree as a failure, so the commit that first reformats
something aborts -- re-stage and commit again. Get it over with in one go, and get a tidy,
reviewable commit out of it:

```bash
pre-commit run black --all-files
```

## Violation ratchet

The pre-commit gate blocks on *every* violation in a staged file, which a codebase with
existing violations can never satisfy. The ratchet is the alternative: record the number of
violations the repo has today, then block any commit that raises it.

Set a baseline path in the config file and the gate switches to ratchet mode:

```json
{ "baseline": "fp-baseline.json" }
```

A relative path resolves against the config file, so the two can be checked in side by side.
`--baseline PATH` overrides it, on `precommit` and `baseline` — `check` has no ratchet mode
and rejects the flag. With no baseline configured, `precommit` behaves exactly as before.

```bash
# Record today's number -- run this once, at adoption
python-fp-lint baseline update --config fp.json

# What is recorded, and where are we now
python-fp-lint baseline show --config fp.json

# The gate
python-fp-lint precommit --config fp.json
```

The file holds one number:

```json
{ "total": 4312 }
```

| Total vs baseline | Result |
|---|---|
| higher | **Commit blocked** (exit 1). Prints the violations in the files you staged, plus a count of the rest. |
| equal | Passes, silently. |
| lower | Passes, rewrites the file to the new total and `git add`s it, so the improvement lands in this commit and cannot be given back. |

`--no-tighten` suppresses the rewrite and the staging. A fall then passes with a warning
naming the new number, so it can still be recorded deliberately:

```
ratchet: 4312 → 4309 (-3) — not tightened (--no-tighten); run `baseline update` to record it
```

That is what CI uses: in a fresh checkout the index is HEAD and nothing is staged, so
`precommit --no-tighten` lints the whole tree and compares. No separate CI command is needed.

```yaml
- run: python-fp-lint precommit --config fp.json --no-tighten
```

### What a blocked commit prints

When your staged files carry violations, only those are listed, then
`N further violation(s) in the rest of the repo, in files you did not stage`. The raw list
runs to thousands of lines on the codebases this exists for, and the regression is almost
always in what you just touched. `check` still prints everything.

When they carry none, there is nothing local to show, so the whole list is printed instead
of an empty report, capped at 50 entries with a trailing
``… and N more (run `check` for the full list)``. That covers CI, where nothing is staged
at all, and the stale-baseline case — after a pull or a merge the total can sit above the
recorded number while everything you staged is clean.

`--format json` in ratchet mode carries two counts, because the printed list is a subset:

| Key | Is |
|---|---|
| `violation_count` | the repo-wide total — the number the ratchet compares |
| `reported_violation_count` | the length of the `violations` array |
| `ratchet` | `{ "baseline": N, "total": N, "tightened": bool }` |

`python-fp-lint schema` describes them under `precommit_ratchet_output`. For `check`,
`violation_count` is still the length of `violations`.

### What the total counts

Every violation from all three backends, flat and unweighted — ast-grep, Ruff and beniget.
The tree that gets counted is the **index**, not your working tree: `precommit` writes the
whole index into a temp directory with `git checkout-index` and lints that. Untracked files
are not counted, because they are not part of the commit; unstaged edits are not counted
either, because they are not part of the commit yet.

The whole index is written, not just the `.py` files, so a `pyproject.toml` or `ruff.toml`
carrying `per-file-ignores` applies exactly as it does when you run Ruff yourself. (Ruff's
`exclude` / `extend-exclude` are not in that set: the gate always names paths explicitly,
and Ruff honours those settings for explicitly named paths only under `force-exclude`. Use
this project's own `exclude` key instead.) Materializing the config files is why the number
CI computes matches the number you get locally with a dirty tree, and why merely touching
an excluded file does not move it.

Two states are refused rather than counted, because both would silently under-count and
auto-tighten would then bank the shortfall:

- **An unmerged index.** `git commit` refuses one anyway; a manual or CI run exits 2.
- **A tracked file git declined to write.** Every tracked `.py` file is checked off against
  `git ls-files` after materialization; a shortfall exits 2 naming the first missing path.

A **sparse checkout** is counted in full: the index is the whole index whether or not your
worktree materializes all of it, so a file outside your cone still contributes.

Two things the number is sensitive to:

- **`C901`, `PLR0915` and `PLR0917` are ceiling rules**, so the total moves when
  `max_complexity`, `max_statements` or `max_positional_args` change, not only when code
  changes. Editing a rule file or changing
  `ruff_select` / `ast_grep_rules` does the same. The baseline records no fingerprint of the
  ruleset, so **re-run `baseline update` deliberately after any such change** — otherwise the
  ratchet banks a windfall from a raised ceiling, or blocks every commit over a new rule.
- **Deleting a file lowers the total.** A total-based ratchet cannot tell debt paid off from
  debt deleted. This is a known and accepted property.

Ratchet mode always enforces `--strict`: a missing `ast-grep` or `ruff` contributes zero
violations, which would read as an improvement and tighten the baseline toward zero.

### With the pre-commit framework

Two things look odd the first time and are both by design.

**The filenames pre-commit passes are ignored.** The framework hands each hook the files it
selected for the commit; ratchet mode measures the whole repo, so there is nothing useful to
do with a subset. The total is a whole-repo number or it is not a ratchet.

**A tightening run fails that commit.** When the total falls, the hook rewrites
`fp-baseline.json` and `git add`s it — so pre-commit sees a modified file, reports
`files were modified by this hook`, and fails the run. Nothing is wrong: the lower number is
already staged, and re-running `git commit` succeeds. This is exactly how the Black hook
behaves when it reformats something.

## Architecture

```
python_fp_lint/
├── lint_gate.py           # Unified LintGate (ast-grep + Ruff + beniget)
├── reassignment_gate.py   # beniget def-use chain analysis (called by LintGate)
├── result.py              # LintResult, LintViolation dataclasses
├── rules_meta.py          # Rule metadata reader (for CLI rules/schema commands)
├── precommit.py           # Staged-blob linting for the git commit gate
├── hook_check.py          # PreToolUse event handling behind `hook-check`
├── output.py              # emit() for command output; CLI logging for diagnostics
├── settings.py            # Config layers (UNSET), the config-file adapter, resolve_settings
├── reports.py             # Report types: each renders a command's output and exit code
├── ratchets.py            # Ratchet protocol: NoRatchet (staged check), BaselineRatchet
├── ratchet.py             # Whole-index total, verdict and auto-tighten
├── baseline.py            # The ratchet's baseline file
├── __init__.py            # Public API: LintGate, LintSettings, load_settings, LintResult, LintViolation
├── __main__.py            # CLI entry point (text + JSON output)
├── sgconfig.yml           # ast-grep configuration
├── rules/                 # 36 ast-grep rule files (.yml)
└── disabled-rules/        # Rules kept for reference; outside rules/ because ast-grep scans it recursively

hooks/
├── lint-check.sh          # Claude Code PreToolUse hook (Edit + Write)
└── lib/hash.sh            # Portable MD5 helper for lock file paths

bin/
└── lint                   # on/off/status/toggle CLI

commands/
└── lint.md                # /lint slash command for Claude Code

installer/
├── common.sh                     # Shared sh scaffolding for the 6 scripts below
├── precommit_yaml.py             # Shared .pre-commit-config.yaml insert/remove
└── pyrightconfig.example.json    # Seeded into a project by the Pyright installer

install-claude-hook.sh            # Wires hook into a project's .claude/settings.json
uninstall-claude-hook.sh          # Undoes install-claude-hook.sh
install-precommit-lint.sh         # Wires the lint gate into .pre-commit-config.yaml
uninstall-precommit-lint.sh       # Undoes install-precommit-lint.sh
install-precommit-pyright.sh      # Wires Pyright into .pre-commit-config.yaml
uninstall-precommit-pyright.sh    # Undoes install-precommit-pyright.sh
install-precommit-black.sh        # Wires Black into .pre-commit-config.yaml
uninstall-precommit-black.sh      # Undoes install-precommit-black.sh
.pre-commit-hooks.yaml            # Hook manifest for the pre-commit framework

precommit-scripts/                # This repo's own terminology guard (betterleaks), not shipped
```

Each backend is called in sequence: ast-grep, Ruff, beniget. By default a missing tool is skipped
without error; pass `--strict` to fail loudly instead. The pre-commit hooks always pass it.

## Design Decisions

### Why Ruff (not Flake8)

Ruff reimplements popular Flake8 plugins (pycodestyle, Pyflakes, bugbear, isort, simplify, and more) in Rust, running **10–100x faster** than Flake8 on real codebases. It ships as a single binary with built-in auto-fix — no plugin installation, no version matrix across six packages. The trade-off is that Ruff does not support custom plugins: you cannot extend it with project-specific rules. That's acceptable here because our FP-specific rules live in ast-grep, which is purpose-built for structural pattern matching.

### Why ast-grep (not hand-written AST visitors)

ast-grep uses tree-sitter to parse Python's concrete syntax tree and match against declarative YAML patterns. A rule like "flag `$LIST.append($ITEM)` inside a `for` loop" is a few lines of YAML; the equivalent `ast.NodeVisitor` in Python would be 50+ lines of imperative traversal code. Declarative rules are easier to review, compose (via `any:`, `all:`, `inside:`), and maintain. ast-grep is also written in Rust, so scanning 36 rules across a codebase adds negligible overhead.

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
