# Resolved Settings and Ratchet Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all settings once, up front, from typed input layers into a concrete `LintSettings`, so `LintGate` never reads files and nothing downstream carries `None`; model the baseline as a `Ratchet` behaviour that returns `Report`s.

**Architecture:** Two adapters (config file, CLI arguments) build `ConfigLayer`s in which an unsupplied scalar is `UNSET`. A pure resolver applies CLI > config > default and returns a complete `LintSettings` plus a `Ratchet` (`NoRatchet` or `BaselineRatchet`). Ratchet methods return `Report` objects; the CLI only renders and exits.

**Tech Stack:** Python ≥3.10, dataclasses, `typing.Protocol`, `enum.Enum`, argparse, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-19-resolved-settings-and-ratchet-protocol-design.md`

## Global Constraints

- No `StrEnum` / `(str, Enum)`; plain `Enum` with `auto()`.
- All new dataclasses are `@dataclass(frozen=True)`.
- A collection is never sum-typed with `None` or `Unset`; "not given" is the empty collection.
- `UNSET` appears only in `ConfigLayer` fields and the code that builds or reads layers.
- The repo gate applies to new code: ≤4 positional parameters, McCabe ≤3, ≤10 statements per function. A flat type dispatch is a `match` with `# noqa: C901 -- <reason>`, never a lookup table.
- Every command's stdout, stderr and exit code stay byte-identical. Error strings, verbatim:
  - `config file not found: {path}`
  - `cannot read config file {path}: {exc}`
  - `{name} must be a non-negative integer, got {value!r}`
  - `required lint backend(s) not found: {', '.join(missing)}`
  - `error: no baseline configured; pass --baseline PATH or set "baseline" in the config file`
- Every commit passes `uv run pytest -q` and the self-lint ratchet (total ≤ `fp-baseline.json`).

## Review Focus

1. A JSON `null` for any key (`"baseline": null` ships in `config.example.json`) means "not given", never an error and never the string `"None"`. — Task 1, `test_null_is_unset`.
2. A config file whose top level is not a JSON object (`[]`, `"x"`) is a `ConfigError`, not an `AttributeError` traceback. — Task 1, `test_non_object_top_level_is_a_config_error`.
3. Relative `lint_rules_dir` and `baseline` in a config file resolve against the config file's directory; a relative `--baseline` on the CLI resolves against the cwd. — Task 1 `test_relative_paths_anchor_to_the_config_dir`, Task 4 `test_cli_baseline_is_not_reanchored`.
4. `--strict` with a missing backend *and* a nonexistent `--config` reports the backend, not the config. — Task 5 keeps `test_strict_checks_backends_before_reading_config` passing unmodified in intent.
5. `hook-check` with no `--config` lints with built-in defaults rather than failing. — Task 5, `test_hook_check_without_config_uses_defaults`.

## File Structure

| File | Responsibility |
|---|---|
| `python_fp_lint/settings.py` (new) | `Unset`/`UNSET`, `ConfigLayer`, `layer_from_config_file`, `resolve_settings`, `load_settings`, `resolve_ratchet` |
| `python_fp_lint/lint_gate.py` | concrete `LintSettings`; `LintGate(*, settings)` with no config reading; `require_backends()` |
| `python_fp_lint/output.py` | gains `OutputFormat` |
| `python_fp_lint/reports.py` (new) | `Report` protocol and the five report types; all formatting moves here from `__main__` |
| `python_fp_lint/ratchets.py` (new) | `CommitRequest`, `Ratchet` protocol, `NoRatchet`, `BaselineRatchet` |
| `python_fp_lint/__main__.py` | argparse, `_cli_layer`, wiring, `_finish`; no formatting, no `None` handling |
| `python_fp_lint/hook_check.py` | takes `LintSettings` instead of a config path |
| `python_fp_lint/baseline.py` | loses `resolve_path` (anchoring moves to the config adapter) |

---

### Task 1: Input layers and the config-file adapter

**Files:**
- Create: `python_fp_lint/settings.py`
- Test: `tests/test_settings.py` (new)

**Interfaces:**
- Produces:
  - `class Unset(Enum): UNSET = auto()` and `UNSET = Unset.UNSET`
  - `@dataclass(frozen=True) class ConfigLayer` with fields, all defaulted: `ruff_select: str | Unset = UNSET`, `ast_grep_rules: tuple[str, ...] = ()`, `exclude: tuple[str, ...] = ()`, `max_complexity: int | Unset = UNSET`, `max_statements: int | Unset = UNSET`, `max_positional_args: int | Unset = UNSET`, `rules_dir: str | Unset = UNSET`, `baseline: str | Unset = UNSET`
  - `layer_from_config_file(path: str) -> ConfigLayer`
- Consumes: `ConfigError`, `_validate_ceiling` from `lint_gate`.

Key mapping: config key `lint_rules_dir` → field `rules_dir`; every other key maps to the field of the same name.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py`, each writing `fp.json` under `tmp_path`:
  - `test_missing_keys_are_unset`: `{}` → `layer_from_config_file(p) == ConfigLayer()`.
  - `test_null_is_unset`: every scalar key set to `null` → `== ConfigLayer()`.
  - `test_values_are_carried`: `{"ruff_select": "E,F", "max_statements": 20, "exclude": ["a/"], "ast_grep_rules": ["no-list-append"]}` → `ConfigLayer(ruff_select="E,F", max_statements=20, exclude=("a/",), ast_grep_rules=("no-list-append",))`.
  - `test_empty_ruff_select_is_unset`: `{"ruff_select": ""}` → `.ruff_select is UNSET`.
  - `test_non_list_collections_are_empty`: `{"exclude": "generated/"}` → `.exclude == ()`.
  - `test_relative_paths_anchor_to_the_config_dir`: config in `tmp_path/"cfg"` with `{"lint_rules_dir": "r", "baseline": "b.json"}` → `(rules_dir, baseline) == (str(cfg/"r"), str(cfg/"b.json"))`; absolute values pass through unchanged.
  - `test_invalid_ceiling_names_the_key`: parametrize `"lots"`, `-1`, `True` for `max_statements` → `ConfigError` matching `max_statements must be a non-negative integer`.
  - `test_missing_file`: → `ConfigError` matching `config file not found`.
  - `test_malformed_json`: `"{"` → `ConfigError` matching `cannot read config file`.
  - `test_non_object_top_level_is_a_config_error`: `[]` → `ConfigError` matching `cannot read config file .*: expected a JSON object`.

- [ ] **Step 2: Run** `uv run pytest tests/test_settings.py -q` — expected: collection error, `settings` does not exist.

- [ ] **Step 3: Implement** `Unset`, `UNSET`, `ConfigLayer`, `layer_from_config_file` in `python_fp_lint/settings.py`. Load with the existing missing-file / malformed-JSON messages (move `_load_config` here from `lint_gate`); a non-dict top level raises `ConfigError(f"cannot read config file {path}: expected a JSON object")`. One small helper per field kind: scalar ceiling (null/missing → `UNSET`, else `_validate_ceiling`), non-empty string, list → tuple (else `()`), anchored path.

- [ ] **Step 4: Run** `uv run pytest tests/test_settings.py -q` — expected: all pass.

- [ ] **Step 5: Commit** — `feat: typed config layers with Unset, read by a config-file adapter`.

---

### Task 2: Concrete `LintSettings`, the resolver, and a gate that never reads config

**Files:**
- Modify: `python_fp_lint/lint_gate.py` (`LintSettings`, `LintGate`, remove `Locations`, `_read_config`, `_load_config`, all `_resolve_*`, `resolve_exclude`, `resolve_baseline`, module `_resolve_rules_dir`)
- Modify: `python_fp_lint/settings.py`, `python_fp_lint/__init__.py`
- Modify: every caller and test that builds a gate (`tests/test_lint_gate.py`, `test_config.py`, `test_exclude.py`, `test_max_*.py`, `test_baseline.py`, `test_ratchet.py`, `test_rule_inventory.py`, `test_output.py`, `precommit.py`, `ratchet.py`; `__main__.py` and `hook_check.py` only as far as needed to keep the suite green; Task 5 finishes them)

**Interfaces:**
- Consumes: Task 1's `ConfigLayer`, `UNSET`, `layer_from_config_file`.
- Produces:
  - `@dataclass(frozen=True) class LintSettings`: `ruff_select: str = _DEFAULT_RUFF_SELECT`, `ast_grep_rules: Sequence[str] = ()`, `exclude: Sequence[str] = ()`, `max_complexity: int = 3`, `max_statements: int = 10`, `max_positional_args: int = 4`, `rules_dir: str = field(default_factory=_package_rules_dir)`, `rules_cache_root: str = field(default_factory=_default_rules_cache_root)`
  - `LintGate(*, settings: LintSettings = _DEFAULT_SETTINGS)`; public methods unchanged: `evaluate(changed_files, project_root)`, `is_excluded(path, project_root)`, `filter_excluded(files, project_root)`
  - `resolve_settings(cli: ConfigLayer, file: ConfigLayer, project_root: str) -> LintSettings` (in `settings.py`)
  - `load_settings(config_path: str, project_root: str = ".") -> LintSettings` = `resolve_settings(ConfigLayer(), layer_from_config_file(config_path), project_root)`
  - `python_fp_lint.__all__` = `LintGate`, `LintSettings`, `LintResult`, `LintViolation`, `load_settings`

Resolution, per field: the CLI layer's value if set (non-empty for collections), else the file layer's, else the default. `rules_dir`: an explicit layer value wins unchecked; otherwise the first of `<project_root>/scripts/lint`, then the package dir, that contains `sgconfig.yml` — the package dir always does. Empty `ast_grep_rules` still means "no filter".

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py`:
  - `test_defaults`: `resolve_settings(ConfigLayer(), ConfigLayer(), str(tmp_path)) == LintSettings()`.
  - `test_cli_beats_file_beats_default`: parametrize over `max_complexity`, `max_statements`, `max_positional_args`, `ruff_select`, `exclude`, `ast_grep_rules`: cli value wins over file value; file value wins over default.
  - `test_empty_cli_collection_defers_to_file`: `cli=ConfigLayer(exclude=())`, `file=ConfigLayer(exclude=("g/",))` → `.exclude == ("g/",)`.
  - `test_rules_dir_search`: no layer value, `tmp_path/"scripts"/"lint"/"sgconfig.yml"` present → that dir; absent → `lint_gate._package_rules_dir()`.
  - `test_explicit_rules_dir_wins_unchecked`: `cli=ConfigLayer(rules_dir="/nowhere")` → `"/nowhere"`.
  - `test_gate_does_not_read_config`: monkeypatch `builtins.open` to raise after constructing `LintGate(settings=LintSettings(rules_dir=rules_dir))`; `evaluate` on an empty list still returns `LintResult(passed=True, violations=[])`.
  - In `tests/test_lint_gate.py::TestConstructorGroups` replace the `Locations` tests with: `LintGate(LintSettings())` raises `TypeError` (keyword-only); `LintGate(config_path="x")` raises `TypeError`; `python_fp_lint.load_settings is load_settings`.

- [ ] **Step 2: Run** `uv run pytest tests/test_settings.py tests/test_lint_gate.py -q` — expected: failures on `resolve_settings` / new `LintSettings` fields.

- [ ] **Step 3: Implement** the concrete `LintSettings`, `LintGate(*, settings)`, `resolve_settings`, `load_settings`. The gate's ast-grep run uses `settings.rules_dir` (materializing only when it equals `_package_rules_dir()`, as now) and `settings.rules_cache_root`; Ruff gets the four settings fields directly.

- [ ] **Step 4: Migrate callers and tests**, rewriting each by meaning:

  | Old | New |
  |---|---|
  | `LintGate(locations=Locations(config_path=c))` | `LintGate(settings=load_settings(c))` |
  | `Locations(rules_dir=r)` | `LintSettings(rules_dir=r)` |
  | config plus overrides | `resolve_settings(ConfigLayer(<overrides>), layer_from_config_file(c), ".")` |
  | `gate._resolve_max_statements()` and similar | the field on the resolved `LintSettings` |
  | `_read_config` tests (`test_config.py`) | `layer_from_config_file` assertions |
  | monkeypatched `_read_config` lambdas (`test_lint_gate.py`) | a `LintSettings(...)` built directly |
  | `resolve_baseline` tests | deleted here; Task 4 re-covers them via `resolve_ratchet` |

  Until Task 5, `__main__` keeps its baseline handling working without `gate.resolve_baseline()`: it takes the CLI value, else `layer_from_config_file(args.config).baseline` (already anchored), and treats `UNSET` as "no baseline" in the existing branch.

- [ ] **Step 5: Run** `uv run pytest -q` — expected: all pass. Run `uv run python -m python_fp_lint check --config fp.json python_fp_lint tests installer | tail -1` — expected: the total is ≤ the baseline.

- [ ] **Step 6: Commit** — `refactor!: LintGate takes resolved settings and never reads config`.

---

### Task 3: Reports

**Files:**
- Modify: `python_fp_lint/output.py` (add `OutputFormat`)
- Create: `python_fp_lint/reports.py` (move `_violation_json`, `_violation_text`, `_check_text`, `_check_json`, `_reported_violations`, `_MAX_REPORTED_VIOLATIONS`, `_ratchet_json`, `_ratchet_text`, `_remainder_note`, `_fall_text` from `__main__.py`)
- Test: `tests/test_reports.py` (new)

**Interfaces:**
- Produces:
  - `class OutputFormat(Enum): TEXT = auto(); JSON = auto()` in `output.py`
  - `class Report(Protocol): exit_code: int; stream: Stream; def render(self, fmt: OutputFormat) -> str`
  - `CheckReport(result: LintResult)`: exit `0` if `result.passed` else `1`; stdout.
  - `RatchetReport(verdict: Verdict, violations: Sequence[LintViolation], staged: frozenset[str])`: exit `1` if `verdict.regressed` else `0`; stdout; `render(TEXT)` is `""` when there is nothing to say (unchanged total).
  - `BaselineRecordedReport(total: int, path: str)`: exit 0; stdout; text `baseline recorded: {total} violation(s) -> {path}`; JSON `{"baseline": total, "total": total, "path": path}`, indent 2.
  - `BaselineShownReport(recorded: int, total: int, path: str)`: exit 0; stdout; text `baseline: {recorded}\ncurrent:  {total}\npath:     {path}`; JSON keys `baseline`, `total`, `path`.
  - `NoBaselineReport()`: exit 2; stderr; both formats render the `error: no baseline configured…` string.

- [ ] **Step 1: Write the failing tests** in `tests/test_reports.py`. For `CheckReport` and `RatchetReport`, generate the expected strings from the *current* `__main__._report` and `__main__._report_ratchet` before moving anything: call each under `contextlib.redirect_stdout`, catching `SystemExit` for the exit code, over these 22 combinations — `_report` with a dirty result (two violations, one with `line=0`) and a clean one, × `text`/`json`; and `_report_ratchet` with verdicts regressed `(2, 4, False)`, tightened `(4, 2, True)`, dropped `(4, 2, False)` and equal `(3, 3, False)`, × staged `set()` / `{"a.py"}`, × `text`/`json`, over 60 violations. Hard-code the captured outputs as a parametrized table of `(report, fmt, expected_render, expected_exit)`; the captured text minus its trailing newline is the expected `render`. Add one test each for the three baseline reports' text, JSON, `exit_code` and `stream`.

- [ ] **Step 2: Run** `uv run pytest tests/test_reports.py -q` — expected: import error.

- [ ] **Step 3: Implement** `OutputFormat` and `reports.py` by moving the helpers; `__main__` imports them back so the CLI is untouched in this task.

- [ ] **Step 4: Run** `uv run pytest -q` — expected: all pass.

- [ ] **Step 5: Commit** — `refactor: report objects render command output`.

---

### Task 4: The Ratchet protocol

**Files:**
- Create: `python_fp_lint/ratchets.py`
- Modify: `python_fp_lint/lint_gate.py` (add `require_backends`), `python_fp_lint/settings.py` (add `resolve_ratchet`)
- Test: `tests/test_ratchets.py` (new)

**Interfaces:**
- Consumes: Task 2's `LintGate`, Task 3's reports, `ratchet.total_violations`, `ratchet.apply`, `baseline.read`, `baseline.write`, `precommit.evaluate_staged`, `precommit.staged_python_files`.
- Produces:
  - `require_backends() -> None` in `lint_gate.py`: raises `BackendError(f"required lint backend(s) not found: {', '.join(missing)}")`.
  - `@dataclass(frozen=True) class CommitRequest: paths: Sequence[str] = (); tighten: bool = True`
  - `class Ratchet(Protocol)` with `check_commit(self, repo_root: str, gate: LintGate, request: CommitRequest) -> Report`, `record(self, repo_root: str, gate: LintGate) -> Report`, `show(self, repo_root: str, gate: LintGate) -> Report`
  - `NoRatchet()`: `check_commit` → `CheckReport` of `evaluate_staged` over a temp dir prefixed `python-fp-lint-staged-`; `record`, `show` → `NoBaselineReport()`.
  - `BaselineRatchet(path: str)`: `check_commit` → `require_backends()`, `total_violations`, `apply(..., tighten=request.tighten)`, `RatchetReport(verdict, violations, frozenset(staged_python_files(repo_root)))`; `record` → `require_backends()`, total, `baseline.write`, `BaselineRecordedReport`; `show` → `baseline.read` *first*, then `require_backends()`, total, `BaselineShownReport`.
  - `resolve_ratchet(cli: ConfigLayer, file: ConfigLayer) -> Ratchet` in `settings.py`: CLI baseline, else file baseline, else `NoRatchet()`. A `match` on `Unset`/`str` per layer.

- [ ] **Step 1: Write the failing tests** in `tests/test_ratchets.py`, reusing the git-repo fixtures and helpers pattern from `tests/test_ratchet.py`:
  - `test_resolve_ratchet`: both layers unset → `NoRatchet()`; file only → `BaselineRatchet(file_path)`; CLI wins over file.
  - `test_cli_baseline_is_not_reanchored`: `ConfigLayer(baseline="rel.json")` → `BaselineRatchet("rel.json")`.
  - `test_no_ratchet_record_and_show`: `.exit_code == 2`, `.stream is Stream.STDERR`, render equals the exact no-baseline string in both formats.
  - `test_no_ratchet_blocks_any_staged_violation`: stage `d = {}\nd["k"] = 1\n` → `CheckReport`, `exit_code == 1`.
  - `test_baseline_ratchet_record_writes_the_total` / `test_show_reads_before_linting` (a missing file raises `BaselineError` even with backends monkeypatched missing) / `test_check_commit_tightens` / `test_check_commit_honours_no_tighten`.
  - `test_missing_backend_raises_backend_error`: monkeypatch `lint_gate.missing_backends` → `BackendError` matching `required lint backend\(s\) not found: ruff`.

- [ ] **Step 2: Run** `uv run pytest tests/test_ratchets.py -q` — expected: import error.

- [ ] **Step 3: Implement** `require_backends`, `CommitRequest`, `Ratchet`, `NoRatchet`, `BaselineRatchet`, `resolve_ratchet`.

- [ ] **Step 4: Run** `uv run pytest -q` — expected: all pass.

- [ ] **Step 5: Commit** — `feat: Ratchet protocol with NoRatchet and BaselineRatchet`.

---

### Task 5: Wire the CLI and the hook

**Files:**
- Modify: `python_fp_lint/__main__.py`, `python_fp_lint/hook_check.py`, `python_fp_lint/baseline.py` (delete `resolve_path`, `_from_config`)
- Modify: `tests/test_cli.py`, `tests/test_backends.py`, `tests/test_hook_check.py`, `tests/test_max_*.py` (CLI and hook call sites only)

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  - argparse: `--ruff-select`, `--max-complexity`, `--max-statements`, `--max-positional-args`, `--baseline` and hook-check's `--config` use `default=argparse.SUPPRESS`; `--ast-grep-rules` and `--exclude` keep `default=""`.
  - `_cli_layer(args) -> ConfigLayer`: `getattr(args, name, UNSET)` for scalars; `_split_list` for the two collections; ceilings validated with `_validate_ceiling`.
  - `_finish(report: Report, fmt: OutputFormat) -> NoReturn`: emit `report.render(fmt)` on `report.stream` only if non-empty, then `sys.exit(report.exit_code)`.
  - `hook_check.check_tool_event(tool_name: str, tool_input: Mapping, settings: LintSettings = _DEFAULT_SETTINGS) -> int`; `hook_check.main(settings: LintSettings) -> NoReturn`.
  - Removed: `_build_gate`, `_resolve_baseline_or_exit`, `_require_backends` (use `require_backends`), `_current_total`, `_report`, `_report_ratchet`, `_run_precommit_staged`, `_run_precommit_ratchet`, `baseline.resolve_path`.

`precommit` order is fixed: `_enforce_strict(args)`, then `_git_repo_root()`, then read config into layers. `check` passes project root `"."`; `precommit` and `baseline` pass the repo root; `hook-check` passes `os.getcwd()`, with `ConfigLayer()` as the file layer when no `--config` is given.

- [ ] **Step 1: Capture the before-snapshots** from the current `main` in a temporary worktree (`git worktree add --detach <scratch>/before HEAD`). Run every `--help`, `rules` (text/json), `schema`, `check` on a clean and a dirty file (text/json), `check` with a missing config, `baseline show` with and without a baseline (text/json), and `hook-check` with a blocking `Write` event. Save stdout, stderr and the exit code per command.

- [ ] **Step 2: Write the failing tests:**
  - `tests/test_hook_check.py::test_hook_check_without_config_uses_defaults`: run `python -m python_fp_lint hook-check` with no `--config` on a blocking `Write` event → exit 2, stderr begins `[lint-gate] Blocked: 1 FP violation(s)`.
  - Update `TestEnforceStrict` in `tests/test_backends.py` to expect `BackendError` matching `required lint backend\(s\) not found: ast-grep`.
  - Update `check_tool_event(..., config_path)` call sites to pass `load_settings(config_path)`.

- [ ] **Step 3: Run** `uv run pytest tests/test_hook_check.py tests/test_backends.py -q` — expected: the new and updated tests fail.

- [ ] **Step 4: Implement** the wiring. Each command builds `cli = _cli_layer(args)` and `file = layer_from_config_file(args.config)`, then `settings = resolve_settings(cli, file, root)` and, for `precommit`/`baseline`, `ratchet = resolve_ratchet(cli, file)`; then `_finish(<report>, OutputFormat[args.format.upper()])`.

- [ ] **Step 5: Run** `uv run pytest -q` — expected: all pass. Re-run the Step 1 command set against the working tree and `diff` every capture — expected: no differences. Remove the worktree.

- [ ] **Step 6: Commit** — `refactor!: CLI and hook resolve settings and a ratchet up front`.

---

### Task 6: Docs and the ratchet

**Files:**
- Modify: `README.md` (Python API under "Configuring rules", "Programmatic API", the Architecture tree), `CONTRIBUTING.md` (Architecture), `fp-baseline.json` (via the hook)

- [ ] **Step 1: Update the README examples** to `LintGate(settings=load_settings("fp.json"))` and to `LintGate(settings=LintSettings(max_statements=20, ...))`, and the `LintSettings(max_…)` hints. Add `settings.py`, `ratchets.py` and `reports.py` to both architecture sections. Remove every mention of `Locations`.

- [ ] **Step 2: Run** `uv run pytest tests/test_rule_inventory.py -q` and `grep -n "Locations\|config_path=" README.md CONTRIBUTING.md` — expected: tests pass; grep prints nothing.

- [ ] **Step 3: Run** `uv run python -m python_fp_lint --format json check --config fp.json python_fp_lint tests installer` — expected: no `no-optional-none`, `no-is-not-none` or `no-or-none-fallback` hits remain in `lint_gate.py`, `__main__.py`, `baseline.py` or `settings.py`, except those on `Unset` boundaries.

- [ ] **Step 4: Commit** — `docs: resolved settings and the Ratchet protocol`. The ratchet hook lowers and stages `fp-baseline.json`; re-run the commit once, as documented.
