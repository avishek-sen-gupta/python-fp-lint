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
from python_fp_lint.precommit import (
    git_output,
    materialize_staged,
    remap_to_repo_relative,
)
from python_fp_lint.result import LintResult


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
    return remap_to_repo_relative(result, mapping)


def total_violations(repo_root: str, gate: LintGate) -> LintResult:
    """Lint the whole index. `len(result.violations)` is the ratchet's number."""
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-index-") as workdir:
        return evaluate_index(repo_root, workdir, gate)
