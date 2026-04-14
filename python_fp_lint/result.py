# python_fp_lint/result.py
"""Result types for python-fp-lint."""

from dataclasses import dataclass


@dataclass
class LintViolation:
    rule: str
    file: str
    line: int
    message: str


@dataclass
class LintResult:
    passed: bool
    violations: list[LintViolation]
