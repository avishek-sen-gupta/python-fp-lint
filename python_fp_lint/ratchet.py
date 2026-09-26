# python_fp_lint/ratchet.py
"""The violation ratchet: one whole-repo total that may fall and may not rise.

Lets a codebase with existing violations adopt the linter on day one. The
recorded total is the gate; `precommit`'s strict per-file check is replaced,
not supplemented, when a baseline is configured -- otherwise nothing in a
dirty repo could ever be committed.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass

from python_fp_lint import baseline
from python_fp_lint.lint_gate import LintGate
from python_fp_lint.precommit import git_output, remap_to_repo_relative
from python_fp_lint.result import LintResult


class RatchetError(Exception):
    """The ratchet cannot produce a total it can stand behind.

    Raised for an unusable index as well as for a tightening that could not be
    recorded. Either way the run has no trustworthy number, and `__main__`
    turns it into a one-line exit 2 rather than a total.
    """


def _git(repo_root: str, *args: str) -> str:
    """git_output, with a failure turned into an exit-2 RatchetError.

    `git checkout-index` fails for reasons a user can hit without doing
    anything exotic -- an index holding both `Mod.py` and `mod.py` on a
    case-insensitive filesystem is enough -- and a raw RuntimeError from
    there reaches the user as a traceback.
    """
    try:
        return git_output(repo_root, *args)
    except RuntimeError as exc:
        raise RatchetError(str(exc)) from exc


def _index_paths(repo_root: str, *args: str) -> list[str]:
    """Paths from NUL-separated `git ls-files` output, blanks dropped.

    `-u` prefixes each record with `<mode> <sha> <stage>\\t`, and a plain
    listing has no tab at all, so taking everything after the first tab
    handles both -- and a path containing a tab keeps it, since `-z` is what
    delimits records.
    """
    records = _git(repo_root, "ls-files", "-z", *args).split("\0")
    return [r.split("\t", 1)[-1] for r in records if r]


def _require_mergeable_index(repo_root: str) -> None:
    """Refuse to count an index with unmerged entries.

    `checkout-index` skips a conflicted path and still exits 0, so a run
    mid-conflict would silently under-count. `git commit` refuses with
    unmerged entries anyway, so this only ever fires for a manual or CI
    invocation -- which is exactly where a too-low total would get recorded.
    """
    unmerged = sorted({p for p in _index_paths(repo_root, "-u")})
    if unmerged:
        raise RatchetError(
            f"the index has {len(unmerged)} unmerged path(s), starting with "
            f"{unmerged[0]} -- resolve the conflict before counting the repo"
        )


def _verify_materialized(repo_root: str, dest: str) -> None:
    """Every tracked .py file must have been written. A shortfall raises.

    `checkout-index` reports what it could not write only sometimes; a
    skip-worktree entry it just passes over, exit 0, no diagnostic. Under
    auto-tighten a silent shortfall is unrecoverable -- the missing files'
    violations vanish, the total falls, and the lower number is written and
    staged -- so the materialization is checked rather than trusted.
    """
    expected = {p for p in _index_paths(repo_root) if p.endswith(".py")}
    missing = sorted(expected - set(_python_files_under(dest)))
    if missing:
        raise RatchetError(
            f"git checkout-index did not write {len(missing)} tracked Python "
            f"file(s), starting with {missing[0]} -- refusing to produce a "
            "total from an incomplete index"
        )


def materialize_index(repo_root: str, dest: str) -> None:
    """Write the whole index -- every tracked file -- into dest.

    One `git checkout-index -a`, not one `git show` per file, and git writes
    the blobs itself, so a non-UTF-8 source file never passes through a
    decode. Untracked files are deliberately absent: they are not part of the
    commit, so counting them would block a commit over code that is not being
    made.

    `--ignore-skip-worktree-bits` because a sparse checkout marks everything
    outside the cone skip-worktree, and `checkout-index` would otherwise pass
    over those paths without a word -- turning a monorepo developer's ordinary
    `git commit` into a windfall that auto-tighten then banks. The index is
    the whole index whether or not the worktree materializes all of it.
    """
    os.makedirs(dest, exist_ok=True)
    _require_mergeable_index(repo_root)
    # --prefix is a literal string prepended to each path, so it needs its
    # trailing separator; os.path.join with "" supplies one portably.
    _git(
        repo_root,
        "checkout-index",
        "-a",
        "--ignore-skip-worktree-bits",
        f"--prefix={os.path.join(dest, '')}",
    )
    _verify_materialized(repo_root, dest)


def _python_files_under(root: str) -> list[str]:
    """Root-relative .py paths under root, sorted."""
    return sorted(
        os.path.relpath(os.path.join(dirpath, name), root)
        for dirpath, _dirnames, filenames in os.walk(root)
        for name in filenames
        if name.endswith(".py")
    )


def evaluate_index(repo_root: str, workdir: str, gate: LintGate) -> LintResult:
    """Lint the committable content of every tracked .py file.

    The whole index is materialized into `workdir` and the `.py` files under
    that tree are what gets linted. The total is therefore a function of the
    index by construction: an unstaged worktree edit cannot move it, and CI on
    a fresh checkout agrees with a developer's dirty tree.

    The older, cheaper split -- lint clean files in place, materialize only
    the dirty ones -- is deliberately gone, and with it the "handful of git
    calls rather than one per file" optimisation. That split materialized
    `.py` files alone, so Ruff found no `pyproject.toml` or `ruff.toml` above
    them and its directory-scoped settings -- `per-file-ignores`, and
    `extend-exclude` only where `force-exclude` is set, since the gate always
    names paths explicitly -- applied to a file only while its worktree copy
    happened to be clean. `checkout-index` brings the config files along.
    """
    materialize_index(repo_root, workdir)
    tracked = gate.filter_excluded(_python_files_under(workdir), repo_root)
    if not tracked:
        return LintResult(passed=True, violations=[])

    # Exclusions were applied to the repo-relative names above, and the
    # mapping puts them back on the violations: once written under workdir a
    # file no longer sits at a path the project's globs describe.
    mapping = {os.path.abspath(os.path.join(workdir, p)): p for p in tracked}
    result = gate.evaluate(sorted(mapping), repo_root)
    return remap_to_repo_relative(result, mapping)


def total_violations(repo_root: str, gate: LintGate) -> LintResult:
    """Lint the whole index. `len(result.violations)` is the ratchet's number."""
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-index-") as workdir:
        return evaluate_index(repo_root, workdir, gate)


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

    @property
    def dropped(self) -> bool:
        """The total fell. `dropped and not tightened` means --no-tighten."""
        return self.total < self.recorded


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
