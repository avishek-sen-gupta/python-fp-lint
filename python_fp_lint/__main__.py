# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check [options] file1.py file2.py"""

import argparse
import sys

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.reassignment_gate import ReassignmentGate


def main():
    parser = argparse.ArgumentParser(
        prog="python-fp-lint",
        description="Functional-programming lint rules for Python",
    )
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="Run lint checks on files")
    check.add_argument("files", nargs="+", help="Python files to check")
    check.add_argument("--semgrep-only", action="store_true", help="Run only Semgrep/ast-grep rules")
    check.add_argument("--reassignment-only", action="store_true", help="Run only reassignment checks")

    args = parser.parse_args()
    if args.command != "check":
        parser.print_help()
        sys.exit(1)

    violations = []
    run_lint = not args.reassignment_only
    run_reassignment = not args.semgrep_only

    if run_lint:
        result = LintGate().evaluate(args.files, ".")
        violations.extend(result.violations)

    if run_reassignment:
        result = ReassignmentGate().evaluate(args.files, ".")
        violations.extend(result.violations)

    if not violations:
        print("No violations found.")
        sys.exit(0)

    for v in violations:
        loc = f"{v.file}:{v.line}" if v.line else v.file
        print(f"  [{v.rule}] {loc} — {v.message}")

    print(f"\n{len(violations)} violation(s) found.")
    sys.exit(1)


if __name__ == "__main__":
    main()
