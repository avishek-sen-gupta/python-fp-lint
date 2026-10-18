# python_fp_lint/result.py
"""Result types for python-fp-lint."""

from dataclasses import dataclass


class BackendError(Exception):
    """A lint backend could not be run, so its findings are unknown.

    Deliberately not an empty result: "the linter did not run" and "the code
    is clean" must stay distinguishable. The ratchet treats zero violations
    as an improvement and tightens the baseline, so a silent failure would
    write a baseline of zero and destroy the recorded debt.
    """


@dataclass(frozen=True)
class LintViolation:
    rule: str
    file: str
    line: int
    message: str


@dataclass(frozen=True)
class LintResult:
    passed: bool
    violations: list[LintViolation]
