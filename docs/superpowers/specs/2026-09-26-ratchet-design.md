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
resolution order (CLI > config file > default). It is offered by `precommit` and
`baseline` only: `check` has no ratchet mode, so accepting the flag there would read as
support for one that does not exist.

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
git ls-files -u                                       # must be empty
git checkout-index -a --ignore-skip-worktree-bits \
                      --prefix=<workdir>/             # the whole index, one call
assert {*.py under <workdir>} == {*.py in git ls-files}
lint(*.py under <workdir>)
```

The **whole** index is materialized, not just the `.py` files and not just the dirty
ones. Untracked files are excluded because they are not part of the commit.

Materializing everything is what makes the total a function of the index *by
construction*. An earlier design linted clean files in place and materialized only the
dirty subset, which kept this to a handful of `git show` calls — but it wrote `.py`
files alone, so Ruff found no `pyproject.toml` or `ruff.toml` above them. Ruff resolves
`per-file-ignores` and the rest of its directory-scoped settings from the closest config
file in a scanned file's ancestors, so those settings applied to a file only while its
worktree copy happened to match its index entry. (`exclude` / `extend-exclude` are not
among them: Ruff honours those for an explicitly named path only under `force-exclude`,
and the gate always names paths explicitly. This project's own `exclude` key is the
supported way to drop a file.) Appending a blank
line to an excluded legacy file — leaving the index content byte-identical — changed the
total. `checkout-index` brings the config files along, and the "handful of git calls"
optimisation is deliberately given up for that.

Because the total no longer depends on worktree state, CI on a fresh checkout and a
developer with a dirty tree compute the same number from the same index.

Exclude globs apply against the repo-relative path — the path the file has *inside* the
materialized tree, which mirrors the repo — exactly as `evaluate_staged` does today, and
`remap_to_repo_relative` reports violations at that repo-relative path rather than the
temp one that was scanned.

Git writes the blobs itself, so a tracked file that is not valid UTF-8 is materialized
verbatim rather than decoded. `precommit.materialize_staged`, which the non-ratchet
staged gate still uses, reads and writes the same blobs as bytes for the same reason.

#### The materialization is checked, not trusted

`git checkout-index -a` can decline to write an index entry and still exit 0 with no
diagnostic. Two cases matter, and under auto-tighten both are unrecoverable: the missing
files' violations vanish, the total falls, and the lower number is written and staged.

- **Skip-worktree bits.** A sparse checkout marks everything outside the cone
  skip-worktree, and those paths are passed over silently. A monorepo developer's ordinary
  `git commit` would bank a windfall. `--ignore-skip-worktree-bits` writes them anyway: the
  index is the whole index whether or not the worktree materializes all of it.
- **Unmerged entries.** A conflicted path is skipped and the rest written, exit 0. `git
  commit` refuses with unmerged entries so the hook path is protected, but a manual or CI
  `precommit` / `baseline update` mid-conflict would record a too-low number.

So the index is rejected outright when `git ls-files -u` is non-empty, and after
materialization the `.py` set on disk is asserted against `git ls-files -z`. A shortfall
raises `RatchetError` naming the first missing path — exit 2, never a total. Failures of
the `git` calls themselves raise `RatchetError` too, so they exit 2 rather than as a
traceback (an index holding both `Mod.py` and `mod.py` on a case-insensitive filesystem
is enough to trigger one).

### The verdict

| Condition | Exit | Behaviour |
|---|---|---|
| `total > baseline` | 1 | Print `ratchet: 4312 → 4315 (+3)`, then the regression report below. The baseline file is not touched. |
| `total == baseline` | 0 | Silent. |
| `total < baseline`, tightening | 0 | Rewrite the file to the new total, `git add` it, print `ratchet: 4312 → 4309 (-3)`. |
| `total < baseline`, `--no-tighten` | 0 | Print ``ratchet: 4312 → 4309 (-3) — not tightened (--no-tighten); run `baseline update` to record it``. The file is not touched. |

#### The regression report

The condition is **whether the staged filter produced anything**, not whether anything is
staged. A blocked commit that names no violation is the failure mode this section exists
to prevent, and an empty staged set is only one of the ways to reach it.

**The filter produced something** — the ordinary commit. Only the staged files' violations
are listed, followed by `N further violation(s) in the rest of the repo, in files you did
not stage`, where `N` is `total - len(staged violations)`. This is what makes a
total-based ratchet usable: the raw list is thousands of lines on the codebase this
feature exists for, and the regression is almost always in what the developer just
touched. The full list stays available through `check`.

**The filter produced nothing** — either nothing is staged (CI on a fresh checkout) or
everything staged is clean (a baseline stale against the index, after a pull, a merge or
someone else's commit). There is no local list to show, and showing an empty one blocks a
commit while naming nothing. The full list is printed instead, capped at 50, with a
trailing ``… and N more (run `check` for the full list)`` when it overflows. There is no
"further … elsewhere" line, because there is no *here* for a remainder to be further
than.

#### JSON output

`--format json` in ratchet mode emits `passed`, `ratchet` (`baseline`, `total`,
`tightened`), and **two** counts:

- `violation_count` — the repo-wide total, the number the ratchet compares.
- `reported_violation_count` — the length of the `violations` array, which carries the
  same subset the text output names.

Two counts rather than one because `check`'s invariant is `violation_count ==
len(violations)`, and a filtered or capped ratchet report cannot honour it with a single
field without lying to an agent reading the output. `schema` describes both, and the
`ratchet` object, under `precommit_ratchet_output`.

`--no-tighten` suppresses the rewrite and the `git add`, turning a drop into a pass with
the warning in the table above. This is what CI uses: in a fresh checkout the index is
HEAD and nothing is staged, so `precommit --no-tighten` lints the whole HEAD tree and
compares. No separate CI command is needed.

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
- A `pyproject.toml` with `per-file-ignores` produces the same total whether the ignored
  file's worktree copy is clean or dirty.
- A tracked file that is not valid UTF-8 is linted (Ruff's `E902`) rather than crashing
  the run, in both the clean and the unstaged-edit case.
- A rise fails with exit 1 and leaves the baseline file byte-identical.
- A rise in a repo with violations in unstaged files prints only the staged files'
  violations, plus the count of the remainder.
- A rise with **nothing** staged names the violations rather than printing an empty
  report, and caps the list.
- A rise whose staged files are all clean does the same.
- A sparse checkout counts a file outside the cone, and does not tighten.
- An unmerged index, and a materialization that came up short, each exit 2 without
  producing a total.
- `violation_count` and `reported_violation_count` differ when the report is filtered,
  and `reported_violation_count == len(violations)` always.
- A fall rewrites the baseline and stages it; `git diff --cached` shows the file.
- `--no-tighten` on a fall exits 0, leaves the file byte-identical, and says so.
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
