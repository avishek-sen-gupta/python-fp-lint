# Violation Ratchet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a legacy codebase adopt python-fp-lint on day one by recording its whole-repo violation total in a baseline file that may fall and may not rise.

**Architecture:** Two new modules. `baseline.py` owns the file (`{"total": N}`) and its path resolution — pure I/O, no git, no linting. `ratchet.py` owns the git side: enumerating the index, linting the committable content of every tracked `.py` file, comparing the total to the baseline, and tightening. `precommit` dispatches to the ratchet when a baseline is configured and is otherwise untouched. Before any of that, `lint_gate` is hardened so a backend that fails to run raises instead of reporting zero violations — under auto-tighten that silence would write `{"total": 0}` and destroy the debt record.

**Tech Stack:** Python 3.10+, ast-grep, Ruff (subprocess), beniget, pytest, uv, Black

**Spec:** `docs/superpowers/specs/2026-09-26-ratchet-design.md`

## Global Constraints

- Python 3.10+; no new third-party dependencies.
- Resolution order for every setting is CLI/constructor > config file > built-in default. Follow the existing `resolve_exclude` / `_resolve_max_complexity` idiom.
- A relative path in the config file resolves relative to **the config file**, not the CWD — the rule `lint_rules_dir` already follows.
- Exit codes: `0` clean or tightened, `1` regression, `2` config, baseline, or backend failure.
- With no `baseline` key configured, `precommit` behaviour is **byte-for-byte unchanged**.
- The baseline file content is exactly `{"total": N}` plus a trailing newline. No fingerprint, no timestamp — rejected in the spec.
- Black formats everything; CI runs `black --check` then `pytest`.
- Tests are pytest, grouped in classes, using `tmp_path` and the throwaway-git-repo fixture pattern from `tests/test_precommit.py` (`git init -q --template=` to suppress the developer's global hooks).

## Review Focus

Five ways this bites a real user that no task's happy path covers. Each already has its test assigned to the task that owns the code.

1. **A merge-conflicted or hand-edited baseline file.** Two branches both tighten, git leaves conflict markers in `fp-baseline.json`. Must exit 2 with the path named — never parse as 0 and never tighten. *(Task 3)*
2. **A configured baseline file that does not exist yet.** The first run after adding the config key. Must say "run `python-fp-lint baseline update`", not treat a missing file as a baseline of 0 and block every commit. *(Task 3)*
3. **`git add` of the tightened baseline failing** — the file is gitignored, or lives outside the repo. The file on disk would then record a lower total than the commit does, permanently blocking the next run. Must restore the previous value and exit 2. *(Task 5)*
4. **A tracked file that is not valid UTF-8 or does not parse.** Legacy repos have latin-1 files. `ReassignmentGate._check_file` catches only `(SyntaxError, OSError)`, so a `UnicodeDecodeError` escapes and crashes the whole run. Must be caught. *(Task 4)*
5. **A repo with zero tracked Python files.** `baseline update` must write `{"total": 0}` and `precommit` must pass, not crash on an empty file list or an empty subprocess invocation. *(Task 4)*

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `python_fp_lint/baseline.py` | The baseline file: read, write, resolve its path. No git, no linting. |
| Create | `python_fp_lint/ratchet.py` | Index enumeration, whole-repo total, verdict, tighten-and-stage. |
| Modify | `python_fp_lint/lint_gate.py` | `BackendError`; backends raise instead of returning `[]`; argv chunking; `resolve_baseline`. |
| Modify | `python_fp_lint/precommit.py` | Rename `_git` → `git_output` so `ratchet.py` can use it. Otherwise unchanged. |
| Modify | `python_fp_lint/reassignment_gate.py` | Catch `UnicodeDecodeError` alongside `SyntaxError`/`OSError`. |
| Modify | `python_fp_lint/__main__.py` | `baseline` subcommand, `--baseline`, `--no-tighten`, ratchet dispatch, exit 2 on the new errors. |
| Create | `tests/test_baseline.py` | Baseline file round-trip, corruption, path resolution. |
| Create | `tests/test_ratchet.py` | Index enumeration, total, verdict, tighten, staging. |
| Modify | `tests/test_backends.py` | Backend failures raise; chunking. |
| Modify | `tests/test_cli.py` | `baseline` subcommand; `precommit` ratchet mode end-to-end. |
| Modify | `README.md` | Ratchet section. |
| Modify | `config.example.json` | `"baseline": null` key. |

---

### Task 1: Backend failure stops reading as a clean repo

A backend that times out, cannot be executed, or emits unparseable output currently returns `[]`. That is a quiet false pass today and data loss under a ratchet: zero violations is a drop, so auto-tighten writes `{"total": 0}`, stages it, and the debt record is gone.

**Files:**
- Modify: `python_fp_lint/lint_gate.py:420-470` (`_run_sg`)
- Modify: `python_fp_lint/lint_gate.py:490-527` (`_run_ruff`)
- Test: `tests/test_backends.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `lint_gate.BackendError(Exception)`. `_run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]` and `_run_ruff(ruff_path: str, files: list[str], select: str, max_complexity: int, max_statements: int = ...) -> list[LintViolation]` keep their signatures but now raise `BackendError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backends.py`:

```python
class TestBackendFailuresRaise:
    """A backend that did not run must not report zero violations.

    Under the ratchet, zero reads as an improvement and tightens the baseline
    to 0, destroying the debt record.
    """

    def test_ruff_timeout_raises(self, monkeypatch):
        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="ruff", timeout=30)

        monkeypatch.setattr(lint_gate.subprocess, "run", timeout)
        with pytest.raises(lint_gate.BackendError, match="timed out"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_oserror_raises(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise OSError(7, "Argument list too long")

        monkeypatch.setattr(lint_gate.subprocess, "run", boom)
        with pytest.raises(lint_gate.BackendError, match="ruff"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_unparseable_output_raises(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess,
            "run",
            lambda *_a, **_k: _Completed(stdout="not json at all"),
        )
        with pytest.raises(lint_gate.BackendError, match="unparseable"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_empty_output_is_still_zero_violations(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess, "run", lambda *_a, **_k: _Completed(stdout="")
        )
        assert lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3) == []

    def test_sg_timeout_raises(self, monkeypatch):
        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="sg", timeout=30)

        monkeypatch.setattr(lint_gate.subprocess, "run", timeout)
        with pytest.raises(lint_gate.BackendError, match="timed out"):
            lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])

    def test_sg_ndjson_fallback_still_works(self, monkeypatch):
        line = json.dumps(
            {
                "ruleId": "no-list-append",
                "file": "a.py",
                "range": {"start": {"line": 4}},
                "message": "m",
            }
        )
        monkeypatch.setattr(
            lint_gate.subprocess, "run", lambda *_a, **_k: _Completed(stdout=line)
        )
        [violation] = lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])
        assert violation.rule == "no-list-append"
        assert violation.line == 5

    def test_sg_garbage_output_raises(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess,
            "run",
            lambda *_a, **_k: _Completed(stdout="{ not json\nalso not json"),
        )
        with pytest.raises(lint_gate.BackendError, match="unparseable"):
            lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])
```

Add these imports and the stub at the top of `tests/test_backends.py`, after the existing imports:

```python
import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class _Completed:
    """Stand-in for subprocess.CompletedProcess."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    args: list = field(default_factory=list)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_backends.py::TestBackendFailuresRaise -v`
Expected: FAIL — `AttributeError: module 'python_fp_lint.lint_gate' has no attribute 'BackendError'`

- [ ] **Step 3: Add `BackendError` and make the backends raise**

In `python_fp_lint/lint_gate.py`, add beside the existing `ConfigError`:

```python
class BackendError(Exception):
    """A lint backend could not be run, so its findings are unknown.

    Deliberately not an empty result: "the linter did not run" and "the code
    is clean" must stay distinguishable. The ratchet treats zero violations
    as an improvement and tightens the baseline, so a silent failure would
    write a baseline of zero and destroy the recorded debt.
    """
```

Replace `_run_sg` with:

```python
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
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            f"ast-grep timed out after 30s on {len(files)} file(s)"
        ) from exc
    except OSError as exc:
        raise BackendError(f"ast-grep could not be run: {exc}") from exc

    if not result.stdout.strip():
        return []
    return [_sg_violation(entry) for entry in _sg_entries(result.stdout)]


def _sg_entries(stdout: str) -> list[dict]:
    """ast-grep emits a JSON array, or NDJSON when streaming."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    entries = []
    for line in stdout.strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"ast-grep produced unparseable output: {line[:80]!r}"
            ) from exc
    return entries


def _sg_violation(entry: dict) -> LintViolation:
    return LintViolation(
        rule=entry.get("ruleId", "unknown"),
        file=entry.get("file", ""),
        line=entry.get("range", {}).get("start", {}).get("line", 0) + 1,
        message=entry.get("message", ""),
    )
```

Replace the body of `_run_ruff` (keep its signature) with:

```python
def _run_ruff(
    ruff_path: str,
    files: list[str],
    select: str,
    max_complexity: int,
    max_statements: int = _DEFAULT_MAX_STATEMENTS,
) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                ruff_path,
                "check",
                "--output-format",
                "json",
                "--select",
                select,
                "--ignore",
                _DEFAULT_RUFF_IGNORE,
                # An inline --config beats any pyproject.toml the scanned
                # project happens to carry, so the gate's ceiling is the one
                # that applies.
                "--config",
                f"lint.mccabe.max-complexity={max_complexity}",
                "--config",
                f"lint.pylint.max-statements={max_statements}",
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"ruff timed out after 30s on {len(files)} file(s)") from exc
    except OSError as exc:
        raise BackendError(f"ruff could not be run: {exc}") from exc

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"ruff produced unparseable output: {result.stdout[:80]!r}"
        ) from exc

    return [
        LintViolation(
            rule=entry.get("code", "unknown"),
            file=entry.get("filename", ""),
            line=entry.get("location", {}).get("row", 0),
            message=entry.get("message", ""),
        )
        for entry in entries
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_backends.py -v`
Expected: PASS, including the pre-existing classes.

- [ ] **Step 5: Run the whole suite — this changes shared behaviour**

Run: `uv run pytest tests/ -x -q`
Expected: PASS. If a test asserted that a broken backend yields an empty result, it is now asserting the bug; update it to expect `BackendError`.

- [ ] **Step 6: Format and commit**

```bash
uv run black python_fp_lint/lint_gate.py tests/test_backends.py
git add python_fp_lint/lint_gate.py tests/test_backends.py
git commit -m "fix: a lint backend that fails to run raises instead of reporting zero violations"
```

---

### Task 2: Chunk the argv so a whole-repo scan cannot blow ARG_MAX

`_run_sg` and `_run_ruff` pass every path as argv. Whole-repo linting on a large codebase exceeds `ARG_MAX` and raises `OSError` — which, after Task 1, is a loud `BackendError` rather than a silent zero, but the run still fails. Chunking also bounds each call's work, keeping the 30-second timeout realistic.

**Files:**
- Modify: `python_fp_lint/lint_gate.py` (`_run_sg`, `_run_ruff` from Task 1)
- Test: `tests/test_backends.py`

**Interfaces:**
- Consumes: `lint_gate.BackendError` and the rewritten `_run_sg` / `_run_ruff` from Task 1.
- Produces: `lint_gate._MAX_PATHS_PER_CALL = 1000` and `lint_gate._chunked(items: list[str], size: int = 1000) -> list[list[str]]`. `_run_sg` / `_run_ruff` signatures are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backends.py`:

```python
class TestArgvChunking:
    def test_chunks_at_the_limit(self):
        chunks = lint_gate._chunked([str(i) for i in range(2500)], size=1000)
        assert [len(c) for c in chunks] == [1000, 1000, 500]

    def test_empty_input_yields_no_chunks(self):
        assert lint_gate._chunked([]) == []

    def test_ruff_runs_once_per_chunk_and_concatenates(self, monkeypatch):
        calls = []

        def record(cmd, **_kwargs):
            paths = [a for a in cmd if a.endswith(".py")]
            calls.append(len(paths))
            entry = {
                "code": "F401",
                "filename": paths[0],
                "location": {"row": 1},
                "message": "m",
            }
            return _Completed(stdout=json.dumps([entry]))

        monkeypatch.setattr(lint_gate.subprocess, "run", record)
        files = [f"f{i}.py" for i in range(2500)]
        violations = lint_gate._run_ruff("/usr/bin/ruff", files, "F", 3)
        assert calls == [1000, 1000, 500]
        assert len(violations) == 3

    def test_sg_runs_once_per_chunk_and_concatenates(self, monkeypatch):
        calls = []

        def record(cmd, **_kwargs):
            paths = [a for a in cmd if a.endswith(".py")]
            calls.append(len(paths))
            entry = {
                "ruleId": "no-list-append",
                "file": paths[0],
                "range": {"start": {"line": 0}},
                "message": "m",
            }
            return _Completed(stdout=json.dumps([entry]))

        monkeypatch.setattr(lint_gate.subprocess, "run", record)
        files = [f"f{i}.py" for i in range(2500)]
        violations = lint_gate._run_sg("/usr/bin/sg", "/rules", files)
        assert calls == [1000, 1000, 500]
        assert len(violations) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_backends.py::TestArgvChunking -v`
Expected: FAIL — `AttributeError: module 'python_fp_lint.lint_gate' has no attribute '_chunked'`

- [ ] **Step 3: Implement chunking**

In `python_fp_lint/lint_gate.py`, beside the other module constants:

```python
# Paths per subprocess invocation. A whole-repo scan on a large codebase
# otherwise exceeds ARG_MAX; chunking also bounds each call's work, which is
# what keeps the 30s timeout realistic.
_MAX_PATHS_PER_CALL = 1000


def _chunked(items: list[str], size: int = _MAX_PATHS_PER_CALL) -> list[list[str]]:
    """Split a path list into subprocess-sized batches. Never yields an empty batch."""
    return [items[i : i + size] for i in range(0, len(items), size)]
```

Rename the Task 1 bodies to `_run_sg_once` / `_run_ruff_once` (identical code, no other change) and add the fan-out wrappers under the original names:

```python
def _run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]:
    # The chunk size is passed explicitly rather than left to the default, so
    # it is read at call time -- a default argument binds once at def time and
    # could not be monkeypatched by a test.
    return [
        violation
        for chunk in _chunked(files, _MAX_PATHS_PER_CALL)
        for violation in _run_sg_once(sg_path, rules_dir, chunk)
    ]


def _run_ruff(
    ruff_path: str,
    files: list[str],
    select: str,
    max_complexity: int,
    max_statements: int = _DEFAULT_MAX_STATEMENTS,
) -> list[LintViolation]:
    return [
        violation
        for chunk in _chunked(files, _MAX_PATHS_PER_CALL)
        for violation in _run_ruff_once(
            ruff_path, chunk, select, max_complexity, max_statements
        )
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_backends.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
uv run black python_fp_lint/lint_gate.py tests/test_backends.py
git add python_fp_lint/lint_gate.py tests/test_backends.py
git commit -m "fix: chunk backend argv at 1000 paths so whole-repo scans cannot exceed ARG_MAX"
```

---

### Task 3: The baseline file

One number on disk, plus the path-resolution rule. No git, no linting — this module is pure I/O so its failure modes can be tested without a repo.

**Files:**
- Create: `python_fp_lint/baseline.py`
- Modify: `python_fp_lint/lint_gate.py` (add `baseline` constructor arg and `resolve_baseline`)
- Modify: `config.example.json`
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `baseline.BaselineError(Exception)`
  - `baseline.resolve_path(cli_value: str | None, config_value: str | None, config_path: str | None) -> str | None`
  - `baseline.read(path: str) -> int`
  - `baseline.write(path: str, total: int) -> None`
  - `LintGate(..., baseline: str | None = None)` and `LintGate.resolve_baseline() -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_baseline.py`:

```python
# tests/test_baseline.py
"""The ratchet's baseline file and its path resolution."""

import json

import pytest

from python_fp_lint import baseline
from python_fp_lint.lint_gate import LintGate


class TestReadWrite:
    def test_round_trips(self, tmp_path):
        path = str(tmp_path / "fp-baseline.json")
        baseline.write(path, 4312)
        assert baseline.read(path) == 4312

    def test_writes_exactly_the_total_and_a_newline(self, tmp_path):
        path = tmp_path / "fp-baseline.json"
        baseline.write(str(path), 7)
        assert path.read_text() == '{"total": 7}\n'

    def test_zero_is_a_valid_total(self, tmp_path):
        path = str(tmp_path / "b.json")
        baseline.write(path, 0)
        assert baseline.read(path) == 0


class TestReadRejectsBadFiles:
    """Review Focus 1 and 2: a bad baseline must never parse as zero."""

    def test_missing_file_names_the_fix(self, tmp_path):
        path = str(tmp_path / "absent.json")
        with pytest.raises(baseline.BaselineError, match="baseline update"):
            baseline.read(path)

    def test_merge_conflict_markers_raise(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text('<<<<<<< HEAD\n{"total": 10}\n=======\n{"total": 12}\n>>>>>>> x\n')
        with pytest.raises(baseline.BaselineError, match="cannot read"):
            baseline.read(str(path))

    def test_truncated_json_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text('{"total":')
        with pytest.raises(baseline.BaselineError, match="cannot read"):
            baseline.read(str(path))

    def test_json_list_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_missing_total_key_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"count": 5}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_string_total_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": "4312"}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_negative_total_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": -1}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))

    def test_bool_total_raises(self, tmp_path):
        """`True` is an int in Python. It is not a violation count."""
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"total": True}))
        with pytest.raises(baseline.BaselineError, match="no valid 'total'"):
            baseline.read(str(path))


class TestResolvePath:
    def test_no_config_value_means_no_ratchet(self):
        assert baseline.resolve_path(None, None, "/proj/fp.json") is None

    def test_cli_value_wins(self):
        assert (
            baseline.resolve_path("/tmp/cli.json", "cfg.json", "/proj/fp.json")
            == "/tmp/cli.json"
        )

    def test_cli_value_wins_even_with_no_config_key(self):
        assert baseline.resolve_path("/tmp/cli.json", None, None) == "/tmp/cli.json"

    def test_relative_config_value_resolves_against_the_config_file(self):
        assert (
            baseline.resolve_path(None, "fp-baseline.json", "/proj/cfg/fp.json")
            == "/proj/cfg/fp-baseline.json"
        )

    def test_absolute_config_value_is_left_alone(self):
        assert (
            baseline.resolve_path(None, "/var/b.json", "/proj/fp.json") == "/var/b.json"
        )


class TestGateResolution:
    def test_constructor_beats_config_file(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text(json.dumps({"baseline": "from-config.json"}))
        gate = LintGate(config_path=str(cfg), baseline="/tmp/from-ctor.json")
        assert gate.resolve_baseline() == "/tmp/from-ctor.json"

    def test_falls_back_to_config_file(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text(json.dumps({"baseline": "b.json"}))
        gate = LintGate(config_path=str(cfg))
        assert gate.resolve_baseline() == str(tmp_path / "b.json")

    def test_none_when_nothing_configured(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text("{}")
        assert LintGate(config_path=str(cfg)).resolve_baseline() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_baseline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'python_fp_lint.baseline'`

- [ ] **Step 3: Write `baseline.py`**

Create `python_fp_lint/baseline.py`:

```python
# python_fp_lint/baseline.py
"""The ratchet's baseline file: one whole-repo violation total.

Deliberately just `{"total": N}`. No fingerprint of the ruleset is recorded,
so changing `max_complexity`, `max_statements`, `ruff_select`, `ast_grep_rules`
or a rule file moves the total for reasons unrelated to the code. Re-run
`baseline update` after any such change.
"""

import json
import os


class BaselineError(Exception):
    """The baseline file is missing, unreadable, or holds no valid total."""


def resolve_path(
    cli_value: str | None, config_value: str | None, config_path: str | None
) -> str | None:
    """Baseline file in force: CLI > config file > none (the ratchet is off).

    A relative path in the config file is relative to the config file itself,
    so a config can be checked in beside the baseline it names -- the rule
    lint_rules_dir already follows.
    """
    if cli_value:
        return cli_value
    if not config_value:
        return None
    if config_path:
        base = os.path.dirname(os.path.abspath(config_path))
        return os.path.join(base, config_value)
    return config_value


def read(path: str) -> int:
    """The recorded total, or BaselineError.

    Never falls back to a default. A baseline that cannot be read is not a
    baseline of zero: zero would read as a clean repo and let every commit
    through, which is the opposite of what the file is for.
    """
    if not os.path.exists(path):
        raise BaselineError(
            f"baseline file not found: {path} "
            "-- run `python-fp-lint baseline update` to create it"
        )
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineError(f"cannot read baseline file {path}: {exc}") from exc

    total = data.get("total") if isinstance(data, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BaselineError(f"baseline file {path} has no valid 'total': {total!r}")
    return total


def write(path: str, total: int) -> None:
    """Record a new total, replacing whatever was there."""
    with open(path, "w") as f:
        json.dump({"total": total}, f)
        f.write("\n")
```

- [ ] **Step 4: Wire it into `LintGate`**

In `python_fp_lint/lint_gate.py`, add the import beside the others:

```python
from python_fp_lint import baseline as baseline_file
```

Add `baseline: str | None = None` as the last keyword parameter of `LintGate.__init__`, with `self.baseline = baseline` beside the other assignments. Then add, next to `resolve_exclude`:

```python
    def resolve_baseline(self) -> str | None:
        """Baseline file in force: constructor > config file > none."""
        return baseline_file.resolve_path(
            self.baseline, self._config("baseline"), self.config_path
        )
```

- [ ] **Step 5: Add the key to `config.example.json`**

Add `"baseline": null,` as the second key, directly after `"lint_rules_dir": null,`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_baseline.py -v`
Expected: PASS (19 tests).

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 8: Format and commit**

```bash
uv run black python_fp_lint/baseline.py python_fp_lint/lint_gate.py tests/test_baseline.py
git add python_fp_lint/baseline.py python_fp_lint/lint_gate.py tests/test_baseline.py config.example.json
git commit -m "feat: add the ratchet baseline file and its path resolution"
```

---

### Task 4: Lint the index and total it up

The total must describe the tree a commit would record — the index, not the worktree. A worktree total would count unstaged edits, so an unstaged fix would tighten the baseline below what the repo actually contains and block every subsequent commit.

**Files:**
- Create: `python_fp_lint/ratchet.py`
- Modify: `python_fp_lint/precommit.py` (rename `_git` → `git_output`, update its three call sites)
- Modify: `python_fp_lint/reassignment_gate.py:38` (catch `UnicodeDecodeError`)
- Test: `tests/test_ratchet.py`

**Interfaces:**
- Consumes: `LintGate` (with `filter_excluded`, `evaluate`), `precommit.materialize_staged(repo_root, paths, dest) -> dict[str, str]`.
- Produces:
  - `precommit.git_output(repo_root: str, *args: str) -> str` (renamed from `_git`)
  - `ratchet.index_python_files(repo_root: str) -> list[str]`
  - `ratchet.unstaged_modified(repo_root: str) -> set[str]`
  - `ratchet.evaluate_index(repo_root: str, workdir: str, gate: LintGate) -> LintResult`
  - `ratchet.total_violations(repo_root: str, gate: LintGate) -> LintResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ratchet.py`:

```python
# tests/test_ratchet.py
"""The violation ratchet: index enumeration, total, verdict, tighten."""

import os
import subprocess

import pytest

from python_fp_lint import ratchet
from python_fp_lint.lint_gate import LintGate

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG = os.path.join(REPO_ROOT, "config.example.json")

# Two violations: a subscript mutation and a dict.update call.
DIRTY = 'd = {}\nd["k"] = 1\nd.update({"j": 2})\n'
CLEAN = "x = 1\n"


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one committed clean file.

    `--template=` suppresses the user's init.templateDir: these repos must not
    inherit whatever global hooks the developer's machine installs.
    """
    _git(tmp_path, "init", "-q", "--template=")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "mod.py").write_text(CLEAN)
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _gate():
    return LintGate(config_path=CONFIG)


def _total(repo):
    return len(ratchet.total_violations(str(repo), _gate()).violations)


class TestIndexEnumeration:
    def test_lists_tracked_python_files(self, repo):
        (repo / "notes.txt").write_text("hi\n")
        _git(repo, "add", "notes.txt")
        _git(repo, "commit", "-qm", "notes")
        assert ratchet.index_python_files(str(repo)) == ["mod.py"]

    def test_untracked_file_is_not_in_the_index(self, repo):
        (repo / "new.py").write_text(CLEAN)
        assert ratchet.index_python_files(str(repo)) == ["mod.py"]

    def test_staged_addition_is_in_the_index(self, repo):
        (repo / "new.py").write_text(CLEAN)
        _git(repo, "add", "new.py")
        assert sorted(ratchet.index_python_files(str(repo))) == ["mod.py", "new.py"]

    def test_staged_deletion_leaves_the_index(self, repo):
        _git(repo, "rm", "-q", "mod.py")
        assert ratchet.index_python_files(str(repo)) == []

    def test_unstaged_edit_is_reported_dirty(self, repo):
        (repo / "mod.py").write_text(CLEAN + "y = 2\n")
        assert ratchet.unstaged_modified(str(repo)) == {"mod.py"}

    def test_clean_worktree_has_nothing_dirty(self, repo):
        assert ratchet.unstaged_modified(str(repo)) == set()


class TestTotal:
    def test_counts_all_three_backends(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        assert _total(repo) == 2

    def test_untracked_file_does_not_count(self, repo):
        """Review Focus 5's sibling: an untracked file is not in the commit."""
        (repo / "loose.py").write_text(DIRTY)
        assert _total(repo) == 0

    def test_unstaged_edit_is_counted_from_the_index_not_the_worktree(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        (repo / "mod.py").write_text(CLEAN)  # fixed, but not staged
        assert _total(repo) == 2

    def test_unstaged_new_violations_do_not_count(self, repo):
        (repo / "mod.py").write_text(DIRTY)  # dirty in worktree only
        assert _total(repo) == 0

    def test_worktree_deletion_is_counted_from_the_index(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        os.unlink(repo / "mod.py")  # deleted, not staged
        assert _total(repo) == 2

    def test_excluded_files_do_not_count(self, tmp_path, repo):
        (repo / "gen.py").write_text(DIRTY)
        _git(repo, "add", "gen.py")
        gate = LintGate(config_path=CONFIG, exclude=["gen.py"])
        assert ratchet.total_violations(str(repo), gate).violations == []

    def test_empty_repo_totals_zero(self, tmp_path):
        """Review Focus 5: no tracked Python files at all."""
        _git(tmp_path, "init", "-q", "--template=")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        assert _total(tmp_path) == 0


class TestUndecodableFiles:
    def test_latin1_file_does_not_crash_the_run(self, repo):
        """Review Focus 4: legacy repos have non-UTF-8 files."""
        (repo / "legacy.py").write_bytes(b"# caf\xe9\nx = 1\n")
        _git(repo, "add", "legacy.py")
        _total(repo)  # must not raise


class TestChunkedRepo:
    def test_same_total_whether_chunked_or_not(self, repo, monkeypatch):
        """A repo linted in several subprocess batches totals the same."""
        for i in range(5):
            (repo / f"m{i}.py").write_text(DIRTY)
        _git(repo, "add", "-A")
        whole = _total(repo)

        monkeypatch.setattr(lint_gate, "_MAX_PATHS_PER_CALL", 2)
        assert _total(repo) == whole == 10
```

Add `from python_fp_lint import lint_gate` to the imports at the top of `tests/test_ratchet.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ratchet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'python_fp_lint.ratchet'`

- [ ] **Step 3: Make `precommit._git` importable**

In `python_fp_lint/precommit.py`, rename `_git` to `git_output` and give it a docstring, updating its three call sites (`staged_python_files`, `materialize_staged.write_blob`):

```python
def git_output(repo_root: str, *args: str) -> str:
    """Run git in repo_root and return stdout, raising on a non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout
```

- [ ] **Step 4: Catch `UnicodeDecodeError` in the reassignment gate**

In `python_fp_lint/reassignment_gate.py`, widen the `_check_file` guard. `UnicodeDecodeError` is a `ValueError`, not an `OSError`, so it currently escapes and crashes the whole run on any latin-1 file:

```python
        try:
            with open(filepath) as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, UnicodeDecodeError, OSError):
            return []
```

- [ ] **Step 5: Write `ratchet.py`**

Create `python_fp_lint/ratchet.py`:

```python
# python_fp_lint/ratchet.py
"""The violation ratchet: one whole-repo total that may fall and may not rise.

Lets a codebase with existing violations adopt the linter on day one. The
recorded total is the gate; `precommit`'s strict per-file check is replaced,
not supplemented, when a baseline is configured -- otherwise nothing in a
dirty repo could ever be committed.
"""

import os
import tempfile

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.precommit import git_output, materialize_staged
from python_fp_lint.result import LintResult, LintViolation


def index_python_files(repo_root: str) -> list[str]:
    """Repo-relative .py paths in the index -- the tree a commit would record.

    Untracked files are deliberately absent: they are not part of the commit,
    so counting them would block a commit over code that is not being made.
    """
    out = git_output(repo_root, "ls-files", "-z")
    return [p for p in out.split("\0") if p.endswith(".py")]


def unstaged_modified(repo_root: str) -> set[str]:
    """Repo-relative paths whose worktree content differs from the index.

    Includes worktree deletions, whose index content is still committable.
    """
    out = git_output(repo_root, "diff", "--name-only", "-z")
    return {p for p in out.split("\0") if p}


def evaluate_index(repo_root: str, workdir: str, gate: LintGate) -> LintResult:
    """Lint the committable content of every tracked .py file.

    A file whose worktree copy matches its index entry is linted in place;
    only the dirty ones are materialized from `git show :path`. That keeps
    this to a handful of git calls rather than one per file, which matters on
    the large codebases the ratchet exists for.
    """
    tracked = gate.filter_excluded(index_python_files(repo_root), repo_root)
    if not tracked:
        return LintResult(passed=True, violations=[])

    dirty = unstaged_modified(repo_root)
    mapping = materialize_staged(repo_root, [p for p in tracked if p in dirty], workdir)
    mapping.update(
        {
            os.path.abspath(os.path.join(repo_root, p)): p
            for p in tracked
            if p not in dirty
        }
    )

    result = gate.evaluate(sorted(mapping), repo_root)

    # Report repo-relative paths rather than the temp ones we scanned.
    violations = [
        LintViolation(
            rule=v.rule,
            file=mapping.get(os.path.abspath(v.file), v.file),
            line=v.line,
            message=v.message,
        )
        for v in result.violations
    ]
    return LintResult(passed=len(violations) == 0, violations=violations)


def total_violations(repo_root: str, gate: LintGate) -> LintResult:
    """Lint the whole index. `len(result.violations)` is the ratchet's number."""
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-index-") as workdir:
        return evaluate_index(repo_root, workdir, gate)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ratchet.py -v`
Expected: PASS (15 tests).

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS — `test_precommit.py` exercises the renamed `git_output` indirectly.

- [ ] **Step 8: Format and commit**

```bash
uv run black python_fp_lint/ratchet.py python_fp_lint/precommit.py \
  python_fp_lint/reassignment_gate.py tests/test_ratchet.py
git add python_fp_lint/ratchet.py python_fp_lint/precommit.py \
  python_fp_lint/reassignment_gate.py tests/test_ratchet.py
git commit -m "feat: total the violations in the index, the tree a commit would record"
```

---

### Task 5: The verdict — compare, tighten, stage

**Files:**
- Modify: `python_fp_lint/ratchet.py`
- Test: `tests/test_ratchet.py`

**Interfaces:**
- Consumes: `ratchet.total_violations`, `baseline.read`, `baseline.write`, `baseline.BaselineError`.
- Produces:
  - `ratchet.RatchetError(Exception)`
  - `ratchet.Verdict` — a dataclass with `recorded: int`, `total: int`, `tightened: bool` and a `delta` property (`total - recorded`)
  - `ratchet.apply(repo_root: str, baseline_path: str, total: int, tighten: bool = True) -> Verdict`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ratchet.py`:

```python
class TestVerdict:
    def _baseline(self, repo, total):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), total)
        _git(repo, "add", "fp-baseline.json")
        _git(repo, "commit", "-qm", "baseline")
        return str(path)

    def test_rise_does_not_tighten(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=13)
        assert (verdict.recorded, verdict.total, verdict.delta) == (10, 13, 3)
        assert verdict.tightened is False
        assert baseline.read(path) == 10

    def test_equal_does_not_tighten(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=10)
        assert verdict.tightened is False
        assert baseline.read(path) == 10

    def test_fall_rewrites_the_file(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=7)
        assert (verdict.recorded, verdict.total, verdict.delta) == (10, 7, -3)
        assert verdict.tightened is True
        assert baseline.read(path) == 7

    def test_fall_stages_the_file(self, repo):
        path = self._baseline(repo, 10)
        ratchet.apply(str(repo), path, total=7)
        staged = _git(repo, "diff", "--cached", "--name-only")
        assert "fp-baseline.json" in staged

    def test_no_tighten_leaves_the_file_alone(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=7, tighten=False)
        assert verdict.tightened is False
        assert baseline.read(path) == 10
        assert _git(repo, "diff", "--cached", "--name-only") == ""

    def test_missing_baseline_raises(self, repo):
        with pytest.raises(baseline.BaselineError):
            ratchet.apply(str(repo), str(repo / "absent.json"), total=7)


class TestStagingFailure:
    """Review Focus 3: a failed `git add` must not leave a lowered file behind.

    The file on disk would record a total the commit does not contain, and the
    next run would compare against a number nothing in the repo justifies.
    """

    def test_gitignored_baseline_restores_the_previous_total(self, repo):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), 10)
        (repo / ".gitignore").write_text("fp-baseline.json\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-qm", "ignore the baseline")

        with pytest.raises(ratchet.RatchetError, match="git add"):
            ratchet.apply(str(repo), str(path), total=7)
        assert baseline.read(str(path)) == 10

    def test_no_tighten_does_not_touch_git_at_all(self, repo):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), 10)
        (repo / ".gitignore").write_text("fp-baseline.json\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-qm", "ignore the baseline")

        verdict = ratchet.apply(str(repo), str(path), total=7, tighten=False)
        assert verdict.tightened is False
        assert baseline.read(str(path)) == 10
```

Add `from python_fp_lint import baseline` to the imports at the top of `tests/test_ratchet.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ratchet.py::TestVerdict -v`
Expected: FAIL — `AttributeError: module 'python_fp_lint.ratchet' has no attribute 'apply'`

- [ ] **Step 3: Implement the verdict**

Append to `python_fp_lint/ratchet.py`, and add `import subprocess` and `from dataclasses import dataclass` plus `from python_fp_lint import baseline` to its imports:

```python
class RatchetError(Exception):
    """The baseline could not be tightened, so the run's result is unsafe."""


@dataclass
class Verdict:
    recorded: int
    total: int
    tightened: bool

    @property
    def delta(self) -> int:
        return self.total - self.recorded

    @property
    def regressed(self) -> bool:
        return self.total > self.recorded


def apply(
    repo_root: str, baseline_path: str, total: int, tighten: bool = True
) -> Verdict:
    """Compare the total to the baseline, tightening the record if it fell."""
    recorded = baseline.read(baseline_path)
    if total >= recorded or not tighten:
        return Verdict(recorded=recorded, total=total, tightened=False)
    _tighten(repo_root, baseline_path, recorded, total)
    return Verdict(recorded=recorded, total=total, tightened=True)


def _tighten(repo_root: str, baseline_path: str, recorded: int, total: int) -> None:
    """Record the lower total and stage it, or leave the file as we found it.

    Staging is what makes the ratchet one-way: the improvement lands in the
    same commit that earned it and cannot be given back. If staging fails --
    the file is gitignored, or lives outside the repo -- the lowered number on
    disk would describe a commit that does not exist, so it is rolled back.
    """
    baseline.write(baseline_path, total)
    result = subprocess.run(
        ["git", "add", "--", baseline_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        baseline.write(baseline_path, recorded)
        raise RatchetError(
            f"baseline fell to {total} but `git add {baseline_path}` failed, "
            f"so it was left at {recorded}: {result.stderr.strip()}"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ratchet.py -v`
Expected: PASS (23 tests).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
uv run black python_fp_lint/ratchet.py tests/test_ratchet.py
git add python_fp_lint/ratchet.py tests/test_ratchet.py
git commit -m "feat: ratchet verdict -- a fallen total rewrites and stages the baseline"
```

---

### Task 6: The `baseline` subcommand

**Files:**
- Modify: `python_fp_lint/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ratchet.total_violations`, `baseline.read`, `baseline.write`, `baseline.BaselineError`, `lint_gate.BackendError`, `LintGate.resolve_baseline`, the existing `_git_repo_root()` and `_build_gate(args)`.
- Produces: `python-fp-lint baseline update|show --config PATH [--baseline PATH] [--format json]`. JSON shape: `{"baseline": <int|null>, "total": <int>, "path": "<str>"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
class TestBaselineCommand:
    def _repo(self, tmp_path):
        def git(*args):
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text('d = {}\nd["k"] = 1\n')
        git("add", "mod.py")
        git("commit", "-qm", "init")
        return tmp_path

    def _run(self, repo, *args):
        return subprocess.run(
            [sys.executable, "-m", "python_fp_lint", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def test_update_creates_the_file(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        result = self._run(
            repo, "baseline", "update", "--config", CONFIG, "--baseline", str(path)
        )
        assert result.returncode == 0
        assert json.loads(path.read_text()) == {"total": 1}

    def test_update_overwrites_an_existing_file(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        path.write_text('{"total": 999}\n')
        self._run(
            repo, "baseline", "update", "--config", CONFIG, "--baseline", str(path)
        )
        assert json.loads(path.read_text()) == {"total": 1}

    def test_show_reports_recorded_and_current(self, tmp_path):
        repo = self._repo(tmp_path)
        path = repo / "b.json"
        path.write_text('{"total": 5}\n')
        result = self._run(
            repo,
            "--format",
            "json",
            "baseline",
            "show",
            "--config",
            CONFIG,
            "--baseline",
            str(path),
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {
            "baseline": 5,
            "total": 1,
            "path": str(path),
        }

    def test_show_on_a_missing_file_exits_two(self, tmp_path):
        repo = self._repo(tmp_path)
        result = self._run(
            repo,
            "baseline",
            "show",
            "--config",
            CONFIG,
            "--baseline",
            str(repo / "absent.json"),
        )
        assert result.returncode == 2
        assert "baseline update" in result.stderr

    def test_no_baseline_anywhere_exits_two(self, tmp_path):
        repo = self._repo(tmp_path)
        result = self._run(repo, "baseline", "show", "--config", CONFIG)
        assert result.returncode == 2
        assert "no baseline configured" in result.stderr


class TestBaselineRefusesToGuess:
    """A backend that cannot run contributes zero violations, which would read
    as a clean repo and record a baseline of zero.

    In-process rather than a subprocess, because `_which` falls back to the
    interpreter's own bin directory -- where `ruff` and `ast-grep` live -- so
    no amount of PATH manipulation in a child process makes them unreachable.
    """

    class _Args:
        def __init__(self, config, baseline):
            self.config = config
            self.baseline = baseline
            self.format = "text"
            self.ruff_select = None
            self.ast_grep_rules = None
            self.exclude = None
            self.max_complexity = None
            self.max_statements = None
            self.strict = False

    def test_update_exits_two_without_writing(self, tmp_path, monkeypatch):
        from python_fp_lint.__main__ import _run_baseline_update

        path = tmp_path / "b.json"
        monkeypatch.setattr(
            "python_fp_lint.__main__.missing_backends", lambda: ["ruff"]
        )
        with pytest.raises(SystemExit) as exc:
            _run_baseline_update(self._Args(CONFIG, str(path)))
        assert exc.value.code == 2
        assert not path.exists()
```

`tests/test_cli.py` already imports `json`, `os`, `subprocess` and `sys` and defines `REPO_ROOT` and `CONFIG`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestBaselineCommand -v`
Expected: FAIL — argparse rejects the unknown `baseline` command, exit code 2 with usage text (the assertions on stdout content fail).

- [ ] **Step 3: Implement the subcommand**

In `python_fp_lint/__main__.py`, add the imports:

```python
from python_fp_lint import baseline as baseline_file
from python_fp_lint import ratchet
from python_fp_lint.lint_gate import BackendError
```

Pass the new flag through `_build_gate` — without this, `--baseline` is parsed and silently ignored, because `resolve_baseline()` would only ever see the config file:

```python
def _build_gate(args) -> LintGate:
    return LintGate(
        ruff_select=args.ruff_select or None,
        ast_grep_rules=_split_list(args.ast_grep_rules),
        exclude=_split_list(getattr(args, "exclude", None)),
        max_complexity=getattr(args, "max_complexity", None),
        max_statements=getattr(args, "max_statements", None),
        config_path=args.config or None,
        baseline=getattr(args, "baseline", None),
    )
```

Add the handlers:

```python
def _resolve_baseline_or_exit(args) -> str:
    """The baseline path in force, or exit 2 -- these commands require one."""
    path = _build_gate(args).resolve_baseline()
    if path is None:
        print(
            "error: no baseline configured; pass --baseline PATH or set "
            '"baseline" in the config file',
            file=sys.stderr,
        )
        sys.exit(2)
    return path


def _require_backends() -> None:
    """Exit 2 when a backend is unreachable.

    The ratchet enforces this unconditionally: a missing backend contributes
    zero violations, which reads as an improvement and would tighten the
    baseline toward zero.
    """
    missing = missing_backends()
    if missing:
        print(
            f"error: required lint backend(s) not found: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)


def _current_total(args) -> int:
    _require_backends()
    result = ratchet.total_violations(_git_repo_root(), _build_gate(args))
    return len(result.violations)


def _run_baseline_update(args):
    path = _resolve_baseline_or_exit(args)
    total = _current_total(args)
    baseline_file.write(path, total)
    if args.format == "json":
        json.dump({"baseline": total, "total": total, "path": path}, sys.stdout, indent=2)
        print()
    else:
        print(f"baseline recorded: {total} violation(s) -> {path}")


def _run_baseline_show(args):
    path = _resolve_baseline_or_exit(args)
    recorded = baseline_file.read(path)
    total = _current_total(args)
    if args.format == "json":
        json.dump(
            {"baseline": recorded, "total": total, "path": path}, sys.stdout, indent=2
        )
        print()
    else:
        print(f"baseline: {recorded}\ncurrent:  {total}\npath:     {path}")
```

Rewrite `_enforce_strict` to delegate, so there is one message and one exit path:

```python
def _enforce_strict(args) -> None:
    """Exit 2 when --strict is set and a backend is unreachable.

    Without this, a missing `sg` or `ruff` silently disables whole rule
    families -- an invisible pass, which is the wrong default for a gate.
    """
    if getattr(args, "strict", False):
        _require_backends()
```

Add `--baseline` to `add_rule_flags`, beside `--config`:

```python
        p.add_argument(
            "--baseline",
            default=None,
            metavar="PATH",
            help=(
                "Path to the ratchet baseline file "
                "(overrides the config file's `baseline`)"
            ),
        )
```

Register the subcommand after the `rules` parser:

```python
    # --- baseline ---
    baseline_cmd = sub.add_parser(
        "baseline", help="Record or inspect the ratchet's violation total"
    )
    baseline_sub = baseline_cmd.add_subparsers(dest="baseline_command", required=True)
    add_rule_flags(baseline_sub.add_parser("update", help="Lint the index and record the total"))
    add_rule_flags(baseline_sub.add_parser("show", help="Print the recorded and current totals"))
```

`add_rule_flags` supplies `--config` (required) and `--baseline` to both. Dispatch in `main()`:

```python
    elif args.command == "baseline":
        run = (
            _run_baseline_update
            if args.baseline_command == "update"
            else _run_baseline_show
        )
        _with_config_errors(run, args)
```

Widen the error funnel so every new failure exits 2 with one line instead of a traceback:

```python
def _with_config_errors(run, args):
    """Turn a bad config, baseline or backend into a one-line error and exit 2."""
    try:
        run(args)
    except (
        ConfigError,
        baseline_file.BaselineError,
        ratchet.RatchetError,
        BackendError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
```

Update its call sites for `check` and `precommit` — they already route through `_with_config_errors`, so they inherit this.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k "Baseline" -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
uv run black python_fp_lint/__main__.py tests/test_cli.py
git add python_fp_lint/__main__.py tests/test_cli.py
git commit -m "feat: add the baseline update/show subcommand"
```

---

### Task 7: `precommit` ratchet mode, `--no-tighten`, and the docs

**Files:**
- Modify: `python_fp_lint/__main__.py` (`_run_precommit`, reporting)
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: `python-fp-lint precommit --config PATH [--baseline PATH] [--no-tighten]`. Ratchet mode activates iff a baseline path resolves. JSON output gains `"ratchet": {"baseline": N, "total": N, "tightened": bool}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
class TestPrecommitRatchet:
    DIRTY = 'd = {}\nd["k"] = 1\n'  # one violation
    DIRTIER = 'd = {}\nd["k"] = 1\nd.update({"j": 2})\n'  # two

    def _repo(self, tmp_path, committed, baseline_total):
        def git(*args):
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text(committed)
        # `baseline` comes last: config.example.json carries "baseline": null,
        # and spreading it after would put the key back to null.
        (tmp_path / "fp.json").write_text(
            json.dumps({**json.load(open(CONFIG)), "baseline": "fp-baseline.json"})
        )
        (tmp_path / "fp-baseline.json").write_text(
            json.dumps({"total": baseline_total}) + "\n"
        )
        git("add", "mod.py", "fp.json", "fp-baseline.json")
        git("commit", "-qm", "init")
        return tmp_path

    def _run(self, repo, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "--format",
                "json",
                "precommit",
                "--config",
                str(repo / "fp.json"),
                *args,
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def _git_out(self, repo, *args):
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True
        ).stdout

    def test_equal_total_passes(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        result = self._run(repo)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_rise_fails_and_leaves_the_baseline_alone(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "mod.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo)
        assert result.returncode == 1
        assert json.loads(result.stdout)["ratchet"] == {
            "baseline": 1,
            "total": 2,
            "tightened": False,
        }
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 1}

    def test_fall_tightens_and_stages(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=2)
        (repo / "mod.py").write_text(self.DIRTY)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo)
        assert result.returncode == 0
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 1}
        assert "fp-baseline.json" in self._git_out(repo, "diff", "--cached", "--name-only")

    def test_no_tighten_passes_without_writing(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTIER, baseline_total=2)
        (repo / "mod.py").write_text(self.DIRTY)
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        result = self._run(repo, "--no-tighten")
        assert result.returncode == 0
        assert json.loads((repo / "fp-baseline.json").read_text()) == {"total": 2}

    def test_pre_existing_violations_do_not_block(self, tmp_path):
        """The whole point: a dirty legacy file can still be committed."""
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "mod.py").write_text(self.DIRTY + "# a comment\n")
        subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True)
        assert self._run(repo).returncode == 0

    def test_text_output_names_only_staged_violations(self, tmp_path):
        repo = self._repo(tmp_path, self.DIRTY, baseline_total=1)
        (repo / "other.py").write_text(self.DIRTIER)
        subprocess.run(["git", "add", "other.py"], cwd=repo, check=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "precommit",
                "--config",
                str(repo / "fp.json"),
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 1
        assert "other.py" in result.stdout
        assert "mod.py" not in result.stdout
        assert "1 further violation" in result.stdout


class TestPrecommitWithoutBaselineIsUnchanged:
    def test_any_violation_in_a_staged_file_still_blocks(self, tmp_path):
        def git(*args):
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        (tmp_path / "mod.py").write_text('d = {}\nd["k"] = 1\n')
        git("add", "mod.py")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "python_fp_lint",
                "precommit",
                "--config",
                CONFIG,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )
        assert result.returncode == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::TestPrecommitRatchet -v`
Expected: FAIL — `--no-tighten` is an unrecognized argument, and the passing cases fail because today every violation in a staged file blocks.

- [ ] **Step 3: Implement ratchet mode**

In `python_fp_lint/__main__.py`, add `--no-tighten` to the `precommit` parser only (not `add_rule_flags` — `check` and `baseline` have no use for it), directly after the `precommit.add_argument("files", ...)` call:

```python
    precommit.add_argument(
        "--no-tighten",
        action="store_true",
        help=(
            "Never rewrite or stage the baseline; a fallen total passes with a "
            "warning. Use this in CI, where nothing is staged."
        ),
    )
```

Add the reporter:

```python
def _report_ratchet(verdict, violations, staged: set[str], fmt: str) -> None:
    """Print a ratchet verdict and exit 0 (clean or tightened) or 1 (regression).

    On a regression only the staged files' violations are listed. The raw list
    runs to thousands of lines on the codebases this feature exists for, and
    the regression is almost always in what was just touched; `check` still
    prints everything.
    """
    if fmt == "json":
        payload = {
            "passed": not verdict.regressed,
            "violation_count": len(violations),
            "ratchet": {
                "baseline": verdict.recorded,
                "total": verdict.total,
                "tightened": verdict.tightened,
            },
            "violations": [
                {"rule": v.rule, "file": v.file, "line": v.line, "message": v.message}
                for v in violations
                if v.file in staged
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    elif verdict.regressed:
        print(f"ratchet: {verdict.recorded} → {verdict.total} (+{verdict.delta})")
        local = [v for v in violations if v.file in staged]
        for v in local:
            loc = f"{v.file}:{v.line}" if v.line else v.file
            print(f"  [{v.rule}] {loc} — {v.message}")
        elsewhere = len(violations) - len(local)
        if elsewhere:
            print(f"\n{elsewhere} further violation(s) elsewhere in the repo.")
    elif verdict.tightened:
        print(f"ratchet: {verdict.recorded} → {verdict.total} ({verdict.delta})")

    sys.exit(1 if verdict.regressed else 0)
```

Replace `_run_precommit` with:

```python
def _run_precommit(args):
    repo_root = _git_repo_root()
    gate = _build_gate(args)
    baseline_path = gate.resolve_baseline()
    if baseline_path is None:
        _run_precommit_staged(args, gate, repo_root)
    else:
        _run_precommit_ratchet(args, gate, repo_root, baseline_path)


def _run_precommit_staged(args, gate: LintGate, repo_root: str) -> None:
    """The original gate: every violation in a staged file blocks the commit."""
    _enforce_strict(args)
    # Materialize staged blobs outside the repo: ast-grep and Ruff both honour
    # the enclosing tree's ignore rules, and a temp dir inside it may be skipped.
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-staged-") as workdir:
        result = evaluate_staged(
            repo_root=repo_root,
            workdir=workdir,
            gate=gate,
            paths=args.files or None,
        )
    _report(result, args.format)


def _run_precommit_ratchet(
    args, gate: LintGate, repo_root: str, baseline_path: str
) -> None:
    """The ratchet: the whole-repo total may fall and may not rise.

    This replaces the staged check rather than adding to it. Leaving the
    staged check on would make a dirty legacy repo uncommittable, which is
    the situation the ratchet exists to escape.
    """
    _require_backends()
    result = ratchet.total_violations(repo_root, gate)
    verdict = ratchet.apply(
        repo_root,
        baseline_path,
        total=len(result.violations),
        tighten=not args.no_tighten,
    )
    _report_ratchet(
        verdict, result.violations, set(staged_python_files(repo_root)), args.format
    )
```

Add `from python_fp_lint.precommit import evaluate_staged, staged_python_files` (extending the existing import) and `from python_fp_lint.lint_gate import ConfigError, LintGate, missing_backends` (already imports `LintGate`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 6: Document it in the README**

Add a `## Violation ratchet` section after the existing `## Pre-commit gate` section:

````markdown
## Violation ratchet

The pre-commit gate blocks on *every* violation in a staged file, which a codebase with
existing violations can never satisfy. The ratchet is the alternative: record the number of
violations the repo has today, then block any commit that raises it.

Set a baseline path in the config file and the gate switches to ratchet mode:

```json
{ "baseline": "fp-baseline.json" }
```

A relative path resolves against the config file, so the two can be checked in side by side.
`--baseline PATH` overrides it. With no baseline configured, `precommit` behaves exactly as
before.

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
| equal | Passes. |
| lower | Passes, rewrites the file to the new total and `git add`s it, so the improvement lands in this commit and cannot be given back. |

`--no-tighten` suppresses the rewrite and the staging. That is what CI uses: in a fresh
checkout the index is HEAD and nothing is staged, so `precommit --no-tighten` lints the whole
tree and compares. No separate CI command is needed.

```yaml
- run: python-fp-lint precommit --config fp.json --no-tighten
```

### What the total counts

Every violation from all three backends, flat and unweighted — ast-grep, Ruff and beniget.
The tree that gets counted is the **index**: tracked files, with unstaged edits read from
`git show :path`. Untracked files are not counted, because they are not part of the commit.

Two things the number is sensitive to:

- **`C901` and `PLR0915` are ceiling rules**, so the total moves when `max_complexity` or
  `max_statements` change, not only when code changes. Editing a rule file or changing
  `ruff_select` / `ast_grep_rules` does the same. The baseline records no fingerprint of the
  ruleset, so **re-run `baseline update` deliberately after any such change** — otherwise the
  ratchet banks a windfall from a raised ceiling, or blocks every commit over a new rule.
- **Deleting a file lowers the total.** A total-based ratchet cannot tell debt paid off from
  debt deleted. This is a known and accepted property.

Ratchet mode always enforces `--strict`: a missing `ast-grep` or `ruff` contributes zero
violations, which would read as an improvement and tighten the baseline toward zero.
````

Also add a row to the config table in **Configuring rules**: `"baseline"` — *path to the ratchet baseline file; unset disables the ratchet*.

- [ ] **Step 7: Verify the documented commands actually work**

Run, from a scratch clone or `/tmp` checkout of any dirty repo:

```bash
uv run python -m python_fp_lint baseline update --config config.example.json
uv run python -m python_fp_lint baseline show --config config.example.json
```

Expected: `update` writes the file and prints the total; `show` prints baseline, current and path. Confirm the numbers match `uv run python -m python_fp_lint check --config config.example.json .`

- [ ] **Step 8: Format and commit**

```bash
uv run black python_fp_lint/__main__.py tests/test_cli.py
git add python_fp_lint/__main__.py tests/test_cli.py README.md
git commit -m "feat: ratchet mode for the pre-commit gate, with --no-tighten for CI"
```

---

## Done when

- `uv run pytest tests/ -x -q` passes.
- `uv run black --check .` passes.
- In a repo with violations and a recorded baseline: an added violation blocks the commit, a removed one tightens the file and stages it, and an unrelated edit to a dirty legacy file commits cleanly.
- With no `baseline` key configured, `precommit` blocks exactly as it did before.
