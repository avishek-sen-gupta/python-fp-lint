"""python-fp-lint — functional-programming lint rules for Python."""

from python_fp_lint.result import LintResult, LintViolation
from python_fp_lint.lint_gate import LintGate

__all__ = [
    "LintGate",
    "LintResult",
    "LintViolation",
]
