# python_fp_lint/reassignment_gate.py
"""ReassignmentGate — beniget-based reassignment detection.

Uses def-use chain analysis to detect variables, parameters, or names
that are assigned more than once within the same scope.
"""

import ast
import os
from collections.abc import Sequence

import beniget

from python_fp_lint.result import BackendError, LintResult, LintViolation

# Bindings that are never reassignments. Definitions and imports declare a
# name rather than rebind it, and an `except ... as` name is deleted when its
# handler ends, so each handler binds a fresh one. `with ... as` is not
# deleted, and stays counted.
_NOT_REBINDINGS = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Import,
    ast.ImportFrom,
    ast.alias,
    ast.ExceptHandler,
)


class ReassignmentGate:
    """Detects variable/parameter reassignment in Python files."""

    def evaluate(self, changed_files: Sequence[str], project_root: str) -> LintResult:
        py_files = [
            f
            for f in dict.fromkeys(changed_files)
            if f.endswith(".py") and os.path.exists(f)
        ]
        violations = [v for path in py_files for v in _check_file(path)]
        return LintResult(passed=not violations, violations=violations)


def _check_file(filepath: str) -> list[LintViolation]:
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    duc = beniget.DefUseChains()
    # A syntax error above is left to Ruff, which reports it. Past that
    # point the file is valid Python, so a failure here would otherwise be
    # invisible: zero reassignments, banked by the ratchet as a fall.
    try:
        duc.visit(tree)
    except Exception as exc:
        raise BackendError(f"beniget could not analyse {filepath}: {exc}") from exc

    return [
        violation
        for scope_node, local_defs in duc.locals.items()
        for violation in _rebindings(filepath, scope_node, local_defs)
    ]


def _rebindings(filepath: str, scope_node: ast.AST, local_defs) -> list[LintViolation]:
    """Every binding of a name after its first, within one scope, in order."""
    bindings = [
        (chain.name(), chain.node)
        for chain in local_defs
        if not isinstance(chain.node, _NOT_REBINDINGS)
    ]
    scope = _scope_description(scope_node)
    return [
        LintViolation(
            rule="reassignment",
            file=filepath,
            line=getattr(node, "lineno", 0),
            message=f"'{name}' reassigned (scope: {scope})",
        )
        for name in dict.fromkeys(bound for bound, _ in bindings)
        for node in [n for bound, n in bindings if bound == name][1:]
    ]


def _scope_description(node: ast.AST) -> str:  # noqa: C901 -- one case per scope kind
    match node:
        case ast.Module():
            return "module"
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return f"function {node.name}()"
        case ast.ClassDef():
            return f"class {node.name}"
        case _:
            return type(node).__name__
