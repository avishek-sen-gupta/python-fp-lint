# Resolved settings and the Ratchet protocol — design

Status: agreed 2026-10-19. Implements the "None handling, kind A" cleanup from the
self-lint ratchet work.

## Problem

`LintGate` reads the config file lazily, one key at a time, whenever a setting is
first needed. To let a constructor argument outrank the config file and the config
file outrank a default, every setting carries a third state — "not given" — spelled
`None`. That costs ~50 None-rule violations (`T | None` fields, `is not None` in six
`_resolve_*` methods, `args.x or None`), lets config errors surface mid-run, and
encodes "no baseline" (a *mode*: ratchet off) as a missing *value*.

## Decisions

1. **Absence is explicit and typed, and lives only at the input edge.** A one-member
   enum `Unset` with the constant `UNSET` marks a scalar no source supplied. It
   appears only in `ConfigLayer`, never in resolved settings.
2. **Collections have no `Unset`.** "Not given" is the empty collection, as for
   `ast_grep_rules` and `exclude` today. Never `Sequence[str] | None` or
   `Sequence[str] | Unset`.
3. **`ruff_select` stays a string**, `str | Unset` in a layer and `str` once resolved:
   it is never split, only handed to Ruff's `--select`.
4. **Adapters build layers.** One adapter turns the config file into a `ConfigLayer`
   (a missing key and a JSON `null` both become `UNSET`; relative paths anchor to the
   config file's directory). One turns parsed CLI arguments into a `ConfigLayer`
   (an unpassed flag is absent, via `argparse.SUPPRESS`, and becomes `UNSET`).
5. **One pure resolver applies precedence and defaults**: CLI layer > config layer >
   built-in default, per field. It validates ceilings, so config errors surface
   before any linting. Its output, `LintSettings`, has no `Unset` and no `None`.
6. **`LintGate` never reads a file.** It takes a `LintSettings` (keyword-only) and
   nothing else. `Locations` is removed. Library callers resolve settings first;
   `load_settings(config_path, project_root)` is the one-call convenience.
7. **The rules directory is resolved to a concrete path** by the resolver: explicit
   `rules_dir` > config `lint_rules_dir` > `<project_root>/scripts/lint` > the
   package's own rules, which always exists and so is the unconditional fallback.
8. **The baseline is a behaviour, not a value.** A `Ratchet` protocol with two
   implementations, both providing all three methods:
   - `NoRatchet` — `check_commit` is today's staged check; `record` and `show`
     return a report saying no baseline is configured (exit 2, on stderr).
   - `BaselineRatchet(path)` — `check_commit` is today's whole-index ratchet;
     `record` writes the total; `show` compares recorded against current.
   The resolver maps the baseline layer field: `UNSET → NoRatchet()`,
   a path → `BaselineRatchet(path)`.
9. **Ratchet methods return a `Report`, never raw numbers.** A `Report` carries
   `exit_code: int`, `stream: Stream` and `render(fmt: OutputFormat) -> str`; the
   CLI only emits and exits. `OutputFormat` is a plain `Enum` (no `StrEnum`).
10. **Output is unchanged.** Every command's stdout, stderr and exit code stays
    byte-identical, except that "no baseline configured" moves from `logging` to a
    report on stderr — same bytes.

## Out of scope

None kinds B ("tool not installed"), C ("no match") and D (`_git_visible_files`).
They are independent of settings and get their own change.
