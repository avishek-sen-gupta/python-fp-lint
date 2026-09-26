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


def materialize_index(repo_root: str, dest: str) -> None:
    """Write the whole index -- every tracked file -- into dest.

    One `git checkout-index -a`, not one `git show` per file, and git writes
    the blobs itself, so a non-UTF-8 source file never passes through a
    decode. Untracked files are deliberately absent: they are not part of the
    commit, so counting them would block a commit over code that is not being
    made.
    """
    os.makedirs(dest, exist_ok=True)
    # --prefix is a literal string prepended to each path, so it needs its
    # trailing separator; os.path.join with "" supplies one portably.
    git_output(repo_root, "checkout-index", "-a", f"--prefix={os.path.join(dest, '')}")


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
    them and its directory-scoped settings (`per-file-ignores`,
    `extend-exclude`) applied to a file only while its worktree copy happened
    to be clean. `checkout-index -a` brings the config files along.
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
