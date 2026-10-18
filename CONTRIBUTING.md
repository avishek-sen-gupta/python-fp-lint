# Contributing to python-fp-lint

Thanks for your interest in contributing! python-fp-lint is an experimental project, and contributions are welcome.

## Getting Started

```bash
git clone https://github.com/avishek-sen-gupta/python-fp-lint.git
cd python-fp-lint
uv sync --extra dev
```

That is the whole setup. The lint backends, Ruff and ast-grep, are ordinary Python
dependencies whose wheels ship the binaries, so there is nothing else to install. An `sg`
or `ruff` already on your `PATH` takes precedence over the bundled ones; Ruff must be 0.16
or later, or `PLR0917` silently stops applying.

## Development Workflow

1. **Create a branch** for your feature or fix.
2. **Write tests first.** Tests go in `tests/`. See [Testing](#testing) below.
3. **Implement** the feature or fix.
4. **Format and run the full test suite**: `uv run black python_fp_lint tests && uv run pytest tests/ -x -q`
5. **Open a pull request** against `main`.

## Testing

- Use `pytest` with fixtures for test setup.
- Prefer dependency injection to patching. Where a seam is not injectable, use pytest's
  `monkeypatch`, not `unittest.mock.patch`.
- Use the `tmp_path` fixture for any filesystem tests.
- Rule and backend tests run the real `ast-grep` and `ruff` binaries against fixture files in
  `tmp_path`; that is the point of them. Tests that run `git` must build their environment
  with `tests/gitenv.py`'s `clean_env()`, so a hook's `GIT_*` variables cannot leak in.
- Every bug fix should include a test that fails without the fix.
- Every new feature should have tests.

## Code Style

- **Python 3.10+**, managed with uv and pyproject.toml; formatted with Black.
- Prefer functional style: list comprehensions, `map`, `filter`, `reduce` over mutation-heavy `for` loops.
- Favour small, composable functions. Avoid large monolithic functions.
- Use fully qualified module imports — no relative imports.
- Use dependency injection for external system interfaces (subprocess, file I/O).
- Prefer early return over deeply nested `if/else`.
- Use enums instead of magic strings for fixed value sets.
- Do not use `None` as a default parameter. Use an immutable empty value (`()`,
  `frozenset()`) or a sentinel object — not `[]` or `{}`, which Ruff's `B006` rejects.
- Add logging (not `print`) for progress tracking, especially in loops and long-running tasks.

## Architecture

python-fp-lint is a composable set of lint gates:

- **LintGate** (`python_fp_lint/lint_gate.py`) — runs the ast-grep, Ruff and beniget backends in sequence. Locates binaries, resolves rule files and config, applies the complexity, statement and positional-parameter ceilings, and parses each backend's JSON output into `LintViolation` objects.
- **ReassignmentGate** (`python_fp_lint/reassignment_gate.py`) — uses beniget's def-use chain analysis to detect variable reassignment within a single scope.
- **Result types** (`python_fp_lint/result.py`) — `LintResult` and `LintViolation` dataclasses shared by all gates.

The README's [Architecture](README.md#architecture) section maps the rest of the tree.

## Adding New Rules

### ast-grep rules

Add a new YAML file under `python_fp_lint/rules/`, named after its `id` and following the
`no-<thing>` convention. Give it `id`, `language: python`, a `rule` (`pattern`, `kind`, or a
combination via `any:`/`all:`/`not:`), `message` and `severity`. Add tests to
`tests/test_ast_grep_rules.py`.

The rule list is restated in a few places, and `tests/test_rule_inventory.py` fails until
they all agree. A new rule also needs:

- an entry in `config.example.json`'s `ast_grep_rules`;
- a row in the README's ast-grep table, and the rule counts there bumped.

To disable a rule without deleting it, move it to `python_fp_lint/disabled-rules/`. A
subdirectory of `rules/` does not work: ast-grep scans `rules/` recursively.

### Ruff rules

Add the code to `_DEFAULT_RUFF_SELECT` in `python_fp_lint/lint_gate.py`, then:

- add a matching entry, in the same order, to `_ruff_rules()` in `python_fp_lint/rules_meta.py`;
- update `ruff_select` in `config.example.json` and in the README's config example;
- add a row to the README's Ruff table.

A rule with a numeric ceiling (like `C901`, `PLR0915`, `PLR0917`) also gets a `max_*`
setting threaded through `LintGate`, the CLI and a dedicated test file; follow
`max_positional_args` as the most recent example.

### New gate

Create a new module in `python_fp_lint/` with an `evaluate(changed_files, project_root) -> LintResult` method. Export it from `__init__.py` and wire it into `__main__.py`.

## Reporting Issues

Open an issue on [GitHub](https://github.com/avishek-sen-gupta/python-fp-lint/issues) with:

- A minimal code snippet that triggers (or fails to trigger) the rule
- Expected vs. actual output
- Versions of ast-grep and Ruff if relevant (`ast-grep --version`, `ruff --version`)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE.md).
