# python_fp_lint/reassignment_gate.py
"""ReassignmentGate — beniget-based reassignment detection.

Uses def-use chain analysis to detect variables, parameters, or names
that are assigned more than once within the same scope.
"""

import ast
import os
from collections import defaultdict

import beniget

from python_fp_lint.result import LintResult, LintViolation


class ReassignmentGate:
    """Detects variable/parameter reassignment in Python files."""

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = [
            f for f in dict.fromkeys(changed_files)
            if f.endswith(".py") and os.path.exists(f)
        ]
        if not py_files:
            return LintResult(passed=True, violations=[])

        all_violations = []
        for filepath in py_files:
            all_violations.extend(self._check_file(filepath))

        return LintResult(passed=len(all_violations) == 0, violations=all_violations)

    @staticmethod
    def _check_file(filepath: str) -> list[LintViolation]:
        try:
            with open(filepath) as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, OSError):
            return []

        duc = beniget.DefUseChains()
        try:
            duc.visit(tree)
        except Exception:
            return []

        violations = []
        for scope_node, local_defs in duc.locals.items():
            names: dict[str, list] = defaultdict(list)
            for chain in local_defs:
                node = chain.node
                name = chain.name()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.alias)):
                    continue
                names[name].append(node)

            for name, nodes in names.items():
                if len(nodes) > 1:
                    for node in nodes[1:]:
                        lineno = getattr(node, "lineno", 0)
                        scope_desc = _scope_description(scope_node)
                        violations.append(LintViolation(
                            rule="reassignment",
                            file=filepath,
                            line=lineno,
                            message=f"'{name}' reassigned (scope: {scope_desc})",
                        ))

        return violations


def _scope_description(node: ast.AST) -> str:
    if isinstance(node, ast.Module):
        return "module"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return f"function {node.name}()"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    return type(node).__name__
