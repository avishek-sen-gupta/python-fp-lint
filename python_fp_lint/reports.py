# python_fp_lint/reports.py
"""What a command produces, as a value: the text it prints, where, and how
the process exits. A Report renders itself; the CLI only emits and exits."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from python_fp_lint.output import OutputFormat, Stream
from python_fp_lint.ratchet import Verdict
from python_fp_lint.result import LintResult, LintViolation


class Report(Protocol):
    @property
    def exit_code(self) -> int: ...

    @property
    def stream(self) -> Stream: ...

    def render(self, fmt: OutputFormat) -> str:
        """The output, without a trailing newline; empty when there is none."""
        ...


@dataclass(frozen=True)
class CheckReport:
    """Every violation found, from `check` or the staged pre-commit check."""

    result: LintResult

    @property
    def exit_code(self) -> int:
        return 0 if self.result.passed else 1

    @property
    def stream(self) -> Stream:
        return Stream.STDOUT

    def render(self, fmt: OutputFormat) -> str:
        if fmt is OutputFormat.JSON:
            return _check_json(self.result)
        return _check_text(self.result.violations)


@dataclass(frozen=True)
class RatchetReport:
    """The ratchet's verdict: the repo-wide total against the baseline."""

    verdict: Verdict
    violations: Sequence[LintViolation]
    staged: frozenset[str]

    @property
    def exit_code(self) -> int:
        return 1 if self.verdict.regressed else 0

    @property
    def stream(self) -> Stream:
        return Stream.STDOUT

    def render(self, fmt: OutputFormat) -> str:
        reported, is_local = _reported_violations(self.violations, self.staged)
        if fmt is OutputFormat.JSON:
            return _ratchet_json(self.verdict, self.violations, reported)
        remainder = len(self.violations) - len(reported)
        return "\n".join(_ratchet_text(self.verdict, reported, remainder, is_local))


@dataclass(frozen=True)
class BaselineRecordedReport:
    """`baseline update`: the total just written."""

    total: int
    path: str

    @property
    def exit_code(self) -> int:
        return 0

    @property
    def stream(self) -> Stream:
        return Stream.STDOUT

    def render(self, fmt: OutputFormat) -> str:
        if fmt is OutputFormat.JSON:
            return _baseline_json(self.total, self.total, self.path)
        return f"baseline recorded: {self.total} violation(s) -> {self.path}"


@dataclass(frozen=True)
class BaselineShownReport:
    """`baseline show`: the recorded total beside the current one."""

    recorded: int
    total: int
    path: str

    @property
    def exit_code(self) -> int:
        return 0

    @property
    def stream(self) -> Stream:
        return Stream.STDOUT

    def render(self, fmt: OutputFormat) -> str:
        if fmt is OutputFormat.JSON:
            return _baseline_json(self.recorded, self.total, self.path)
        return (
            f"baseline: {self.recorded}\ncurrent:  {self.total}\npath:     {self.path}"
        )


@dataclass(frozen=True)
class NoBaselineReport:
    """A baseline command run where no baseline is configured. A diagnostic,
    so it goes to stderr whatever the format."""

    @property
    def exit_code(self) -> int:
        return 2

    @property
    def stream(self) -> Stream:
        return Stream.STDERR

    def render(self, fmt: OutputFormat) -> str:
        return (
            "error: no baseline configured; pass --baseline PATH or set "
            '"baseline" in the config file'
        )


def _baseline_json(recorded: int, total: int, path: str) -> str:
    return json.dumps({"baseline": recorded, "total": total, "path": path}, indent=2)


def _violation_json(v: LintViolation) -> dict:
    return {"rule": v.rule, "file": v.file, "line": v.line, "message": v.message}


def _violation_text(v: LintViolation) -> str:
    loc = f"{v.file}:{v.line}" if v.line else v.file
    return f"  [{v.rule}] {loc} — {v.message}"


def _check_text(violations: Sequence[LintViolation]) -> str:
    if not violations:
        return "No violations found."
    return "\n".join(
        [
            *(_violation_text(v) for v in violations),
            f"\n{len(violations)} violation(s) found.",
        ]
    )


def _check_json(result: LintResult) -> str:
    payload = {
        "passed": result.passed,
        "violation_count": len(result.violations),
        "violations": [_violation_json(v) for v in result.violations],
    }
    return json.dumps(payload, indent=2)


_MAX_REPORTED_VIOLATIONS = 50


def _reported_violations(
    violations: Sequence[LintViolation], staged: frozenset[str]
) -> tuple[list, bool]:
    """The subset of the repo's violations a ratchet report shows.

    Normally the staged files' violations. The raw list runs to thousands of
    lines on the codebases this feature exists for, and the regression is
    almost always in what was just touched; `check` still prints everything.

    The condition is whether the filter produced anything, not whether
    anything is staged. Nothing staged is the CI case, but a staged set that
    is entirely clean is just as common -- a baseline stale against the index
    after a pull, a merge or someone else's commit -- and both would otherwise
    block a commit while naming no violation at all. Whenever there is nothing
    local to show, the whole list is shown instead, capped, with the caller
    printing how many were dropped.

    Returns the list and whether it is the local one, which is what decides
    how the caller words the count of everything it left out.
    """
    local = [v for v in violations if v.file in staged]
    if local:
        return local, True
    return list(violations[:_MAX_REPORTED_VIOLATIONS]), False


def _ratchet_json(verdict, violations, reported) -> str:
    payload = {
        "passed": not verdict.regressed,
        # The repo-wide total, which is what the ratchet compares; the
        # length of `violations` below is `reported_violation_count`, and
        # the two differ whenever the report is filtered or capped.
        "violation_count": len(violations),
        "reported_violation_count": len(reported),
        "ratchet": {
            "baseline": verdict.recorded,
            "total": verdict.total,
            "tightened": verdict.tightened,
        },
        "violations": [_violation_json(v) for v in reported],
    }
    return json.dumps(payload, indent=2)


def _ratchet_text(verdict, reported, remainder: int, is_local: bool) -> list[str]:
    """The text report's lines; none at all when the total is unchanged."""
    if verdict.regressed:
        return [
            f"ratchet: {verdict.recorded} → {verdict.total} (+{verdict.delta})",
            *(_violation_text(v) for v in reported),
            *_remainder_note(remainder, is_local),
        ]
    return _fall_text(verdict)


def _remainder_note(remainder: int, is_local: bool) -> list[str]:
    if not remainder:
        return []
    if is_local:
        return [
            f"\n{remainder} further violation(s) in the rest of the repo, "
            "in files you did not stage."
        ]
    return [f"\n… and {remainder} more (run `check` for the full list)"]


def _fall_text(verdict) -> list[str]:
    if verdict.tightened:
        return [f"ratchet: {verdict.recorded} → {verdict.total} ({verdict.delta})"]
    if verdict.dropped:
        # --no-tighten: the only way to reach a fall that was not recorded.
        # Silence here is how a baseline drifts above reality forever.
        return [
            f"ratchet: {verdict.recorded} → {verdict.total} ({verdict.delta}) "
            "— not tightened (--no-tighten); run `baseline update` to record it"
        ]
    return []
