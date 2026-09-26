# Violation Ratchet Design

**Goal:** Let a legacy codebase adopt python-fp-lint on day one. Record the number of
violations that exist today, block any commit that raises it, and tighten the record
automatically whenever it falls.

## Context

`precommit` today blocks a commit if *any* staged file contains *any* violation,
including violations that predate the change being committed. That is the right
default for a clean repo and makes adoption impossible for a dirty one: a codebase
with 4,000 violations cannot make its next commit.

The Claude Code `hook-check` gate already solves a narrower version of this by keeping
only violations inside the edited line range (`violations_in_range`). That works for a
single edit but says nothing about a codebase.

The ratchet is the third policy: a single whole-repo number that may fall and may not rise.

## Design

### The baseline file

A JSON file whose path comes from a new config key, resolved relative to the config
file itself — the same rule `lint_rules_dir` already follows, so a config can be checked
in beside the baseline it names:

```json
{ "baseline": "fp-baseline.json" }
```

Its content is one number:

```json
{ "total": 4312 }
```

A `--baseline PATH` flag overrides the config key, following the project's existing
resolution order (CLI > config file > default).

When no baseline is configured, nothing in this design activates: `precommit` behaves
exactly as it does today.

### What the total counts

Every violation `LintGate.evaluate()` returns, flat and unweighted — ast-grep, Ruff and
beniget together. On this repo's own source, that is 190: 134 ast-grep, 43 Ruff
(including `C901` and `PLR0915`), 13 `reassignment`.

Two consequences the operator owns:

- `C901` and `PLR0915` are ceiling rules, so the total moves when `max_complexity` or
  `max_statements` change, not only when code changes. Editing a `.yml` rule file does
  the same. After any such change, run `baseline update` deliberately — otherwise the
  ratchet banks a windfall (a raised ceiling) or blocks every commit (a new rule). The
  baseline records no fingerprint of the ruleset; this discipline is manual by decision.
- `reassignment` flags every re-binding in a scope, including idiomatic
  `x = ...; x = f(x)`. It typically dominates the total on legacy code. The ratchet only
  reads the delta, so this is harmless, but the headline number is mostly one rule.

### What gets linted

The tree that would exist if the commit landed — the index, not the worktree.

```
tracked   = git ls-files -z                    # the index; untracked files are not in it
dirty     = git diff --name-only -z            # worktree differs from index
lint(f)   = git show :f   if f in dirty
            worktree f    otherwise
```

Untracked files are excluded because they are not part of the commit. Materializing
only the dirty subset keeps this to a handful of `git show` calls rather than one per
file. Materialization reuses `precommit.materialize_staged`, which already writes
`git show :path` blobs under a temp dir outside the repo; it needs only to accept an
arbitrary path list rather than the staged one.

Exclude globs apply against the repo-relative path before materialization, exactly as
`evaluate_staged` does today.

### The verdict

| Condition | Exit | Behaviour |
|---|---|---|
| `total > baseline` | 1 | Print `ratchet: 4312 → 4315 (+3)`, then the violations **in staged files only**, with a trailing count of the rest. The baseline file is not touched. |
| `total == baseline` | 0 | Silent. |
| `total < baseline` | 0 | Rewrite the file to the new total, `git add` it, print `ratchet: 4312 → 4309 (-3)`. |

Printing only the staged files' violations is what makes a total-based ratchet usable:
the raw list is thousands of lines on the codebase this feature exists for, and the
regression is almost always in what the developer just touched. The full list stays
available through `check`. Filtering costs nothing — the violations are already in hand
and the staged set is already known — and it restores the locality a single total
otherwise throws away.

`--no-tighten` suppresses the rewrite and the `git add`, turning a drop into a pass with
a warning. This is what CI uses: in a fresh checkout the index is HEAD and nothing is
staged, so `precommit --no-tighten` lints the whole HEAD tree and compares. No separate
CI command is needed.

### CLI surface

| Command | Does |
|---|---|
| `python-fp-lint baseline update --config fp.json` | Lint the index, write the total. Creates the file if absent, so there is no separate `init`. |
| `python-fp-lint baseline show --config fp.json` | Print the recorded total and the current one. |
| `python-fp-lint precommit --config fp.json` | Ratchet mode iff a baseline is configured. |
| `python-fp-lint precommit --config fp.json --no-tighten` | As above, but never writes or stages. |

`baseline` honours `--format json`, consistent with `check` and `rules`.

### Backend failure must not read as a clean repo

`_run_sg` and `_run_ruff` currently return `[]` on three paths: `subprocess.TimeoutExpired`,
`OSError`, and a missing binary (`_find_sg()`/`_find_ruff()` returning `None`). Today that
is a quiet false pass. Under a ratchet it is data loss:

> a backend fails → zero violations → the total is `0` → `0 < baseline` is a drop →
> auto-tighten writes `{"total": 0}`, stages it, and the commit lands. The debt record is
> gone, and every subsequent commit fails against a baseline of zero.

The fix is to make "did not run" distinguishable from "found nothing". A new
`BackendError` replaces those `return []` statements, propagates out of
`LintGate.evaluate()`, and is caught in `__main__` beside `ConfigError` to exit 2 with a
one-line message. This changes behaviour for `check` and `precommit` too, in both cases
turning a silent false pass into a loud failure; `--strict` remains as the narrower,
earlier check for a missing binary before any work starts.

`json.JSONDecodeError` on backend output is treated the same way — unparseable output is
a failed run, not an empty one. `_run_sg`'s existing NDJSON fallback stays, and only a
failure of both forms raises.

### Argument list length

`_run_sg` and `_run_ruff` pass every file path as argv. Whole-repo linting on a large
codebase exceeds `ARG_MAX` and raises `OSError`, which — before the change above — read
as zero violations. Both calls chunk at 1,000 paths per subprocess and concatenate the
results. Chunking also bounds each call's work, which keeps the existing 30-second
timeout realistic for a whole-repo scan.

## Testing

- The total equals the sum across all three backends for a known fixture.
- A file with unstaged edits is counted from its index content, not its worktree content.
- An untracked file does not contribute to the total.
- A rise fails with exit 1 and leaves the baseline file byte-identical.
- A rise in a repo with violations in unstaged files prints only the staged files'
  violations, plus the count of the remainder.
- A fall rewrites the baseline and stages it; `git diff --cached` shows the file.
- `--no-tighten` on a fall exits 0 and leaves the file byte-identical.
- A missing `ruff` binary raises `BackendError`, exits 2, and does **not** write the
  baseline. Same for a timeout and for unparseable backend output.
- A repo with more than 1,000 files produces the same total as the same repo linted in
  one call.
- No `baseline` key configured leaves `precommit` behaviour unchanged.

## Out of scope

- Per-file, per-rule or per-backend baselines. Rejected in favour of a single total.
- A ruleset fingerprint in the baseline file. Rejected; see the discipline note above.
- Ratchet semantics for `check` and for the Claude Code `hook-check` gate, which keeps
  its `violations_in_range` behaviour.
- Any handling of the delete-a-file loophole (removing a legacy file lowers the total and
  earns credit). Accepted as a known property of a total-based ratchet.
