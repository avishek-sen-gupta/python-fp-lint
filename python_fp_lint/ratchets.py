# python_fp_lint/ratchets.py
"""What a commit, `baseline update` and `baseline show` do, which depends on
whether a baseline is configured. Both ratchets answer with a Report."""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from python_fp_lint import baseline, ratchet
from python_fp_lint.lint_gate import LintGate, require_backends
from python_fp_lint.precommit import evaluate_staged, staged_python_files
from python_fp_lint.reports import (
    BaselineRecordedReport,
    BaselineShownReport,
    CheckReport,
    NoBaselineReport,
    RatchetReport,
    Report,
)


@dataclass(frozen=True)
class CommitRequest:
    """What the commit asks to be checked: `paths` narrows the staged set
    (empty means every staged file); `tighten` lets a fallen total be
    recorded."""

    paths: Sequence[str] = ()
    tighten: bool = True


class Ratchet(Protocol):
    def check_commit(
        self, repo_root: str, gate: LintGate, request: CommitRequest
    ) -> Report:
        """Whether this commit may proceed."""
        ...

    def record(self, repo_root: str, gate: LintGate) -> Report:
        """`baseline update`: record the repo's current total."""
        ...

    def show(self, repo_root: str, gate: LintGate) -> Report:
        """`baseline show`: the recorded total beside the current one."""
        ...


@dataclass(frozen=True)
class NoRatchet:
    """No baseline: every violation in a staged file blocks the commit."""

    def check_commit(
        self, repo_root: str, gate: LintGate, request: CommitRequest
    ) -> Report:
        # Materialize staged blobs outside the repo: ast-grep and Ruff both
        # honour the enclosing tree's ignore rules, and a temp dir inside it
        # may be skipped.
        with tempfile.TemporaryDirectory(prefix="python-fp-lint-staged-") as workdir:
            return CheckReport(evaluate_staged(repo_root, workdir, gate, request.paths))

    def record(self, repo_root: str, gate: LintGate) -> Report:
        return NoBaselineReport()

    def show(self, repo_root: str, gate: LintGate) -> Report:
        return NoBaselineReport()


@dataclass(frozen=True)
class BaselineRatchet:
    """The whole-repo total may fall and may not rise.

    This replaces the staged check rather than adding to it: leaving the
    staged check on would make a dirty legacy repo uncommittable, which is the
    situation the ratchet exists to escape. It always requires both backends,
    since a missing one would read as an improvement.
    """

    path: str

    def check_commit(
        self, repo_root: str, gate: LintGate, request: CommitRequest
    ) -> Report:
        require_backends()
        result = ratchet.total_violations(repo_root, gate)
        verdict = ratchet.apply(
            repo_root, self.path, total=len(result.violations), tighten=request.tighten
        )
        staged = frozenset(staged_python_files(repo_root))
        return RatchetReport(verdict, result.violations, staged)

    def record(self, repo_root: str, gate: LintGate) -> Report:
        total = _current_total(repo_root, gate)
        baseline.write(self.path, total)
        return BaselineRecordedReport(total, self.path)

    def show(self, repo_root: str, gate: LintGate) -> Report:
        # The recorded total first: a missing baseline file is the error to
        # report, whatever else is wrong.
        recorded = baseline.read(self.path)
        return BaselineShownReport(recorded, _current_total(repo_root, gate), self.path)


def _current_total(repo_root: str, gate: LintGate) -> int:
    require_backends()
    return len(ratchet.total_violations(repo_root, gate).violations)
