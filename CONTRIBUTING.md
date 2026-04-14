# Contributing to python-fp-lint

Thanks for your interest in contributing! python-fp-lint is an experimental project, and contributions are welcome.

## Getting Started

```bash
git clone https://github.com/avishek-sen-gupta/python-fp-lint.git
cd python-fp-lint
pip install -e ".[dev]"
```

You will also need [Semgrep](https://semgrep.dev/) installed (`pip install semgrep` or `brew install semgrep`). [ast-grep](https://ast-grep.github.io/) (`sg`) is optional but recommended.

## Development Workflow

1. **Create a branch** for your feature or fix.
2. **Write tests first.** Tests go in `tests/`. See [Testing](#testing) below.
3. **Implement** the feature or fix.
4. **Run the full test suite**: `python -m pytest tests/ -x -q`
5. **Open a pull request** against `main`.

## Testing

- Use `pytest` with fixtures for test setup.
- Use dependency injection instead of `unittest.mock.patch` — inject mock objects directly.
- Use the `tmp_path` fixture for any filesystem tests.
- Unit tests must not perform real I/O (no network, no subprocess calls to Semgrep/ast-grep).
- Every bug fix should include a test that fails without the fix.
- Every new feature should have tests.

## Code Style

- **Python 3.10+**, managed with pip and pyproject.toml.
- Prefer functional style: list comprehensions, `map`, `filter`, `reduce` over mutation-heavy `for` loops.
- Favour small, composable functions. Avoid large monolithic functions.
- Use fully qualified module imports — no relative imports.
- Use dependency injection for external system interfaces (subprocess, file I/O).
- Prefer early return over deeply nested `if/else`.
- Use enums instead of magic strings for fixed value sets.
- Do not use `None` as a default parameter — use empty structures (`[]`, `{}`, etc.).
- Add logging (not `print`) for progress tracking, especially in loops and long-running tasks.

## Architecture

python-fp-lint is a composable set of lint gates:

- **LintGate** (`python_fp_lint/lint_gate.py`) — orchestrates Semgrep and ast-grep backends. Locates binaries, resolves rule files, parses JSON output into `LintViolation` objects.
- **ReassignmentGate** (`python_fp_lint/reassignment_gate.py`) — uses beniget's def-use chain analysis to detect variable reassignment within a single scope.
- **Result types** (`python_fp_lint/result.py`) — `LintResult` and `LintViolation` dataclasses shared by all gates.

## Adding New Rules

### Semgrep rules

Add a new rule entry to `python_fp_lint/semgrep-rules.yml`. Follow the existing naming convention (`no-<thing>`). Each rule needs `id`, `pattern` (or `patterns`), `message`, `severity`, and `languages`.

### ast-grep rules

Add a new YAML file under `python_fp_lint/rules/`. Point it at the Python language and define `rule.pattern` plus `rule.kind` as needed. See existing rules for examples.

### New gate

Create a new module in `python_fp_lint/` with an `evaluate(changed_files, project_root) -> LintResult` method. Export it from `__init__.py` and wire it into `__main__.py`.

## Reporting Issues

Open an issue on [GitHub](https://github.com/avishek-sen-gupta/python-fp-lint/issues) with:

- A minimal code snippet that triggers (or fails to trigger) the rule
- Expected vs. actual output
- Versions of Semgrep/ast-grep if relevant

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE.md).
