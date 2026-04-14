# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check file1.py file2.py

Designed for both human use (text output) and LLM agent use (--format json).
"""

import argparse
import json
import sys

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.rules_meta import list_rules


def _run_check(args):
    gate = LintGate()
    result = gate.evaluate(args.files, ".")
    violations = result.violations

    if args.format == "json":
        payload = {
            "passed": result.passed,
            "violation_count": len(violations),
            "violations": [
                {
                    "rule": v.rule,
                    "file": v.file,
                    "line": v.line,
                    "message": v.message,
                }
                for v in violations
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        if not violations:
            print("No violations found.")
        else:
            for v in violations:
                loc = f"{v.file}:{v.line}" if v.line else v.file
                print(f"  [{v.rule}] {loc} — {v.message}")
            print(f"\n{len(violations)} violation(s) found.")

    sys.exit(0 if result.passed else 1)


def _run_rules(args):
    rules = list_rules()

    if args.format == "json":
        json.dump(rules, sys.stdout, indent=2)
        print()
    else:
        for r in rules:
            backend = r["backend"]
            print(f"  [{backend:8s}] {r['id']}")
            print(f"             {r['message']}")


def _run_schema(_args):
    schema = {
        "check_output": {
            "description": "Output of the 'check' command",
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "True if no violations found",
                },
                "violation_count": {
                    "type": "integer",
                    "description": "Number of violations",
                },
                "violations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule": {
                                "type": "string",
                                "description": "Rule ID that was violated",
                            },
                            "file": {
                                "type": "string",
                                "description": "Path to the file",
                            },
                            "line": {
                                "type": "integer",
                                "description": "Line number (1-based, 0 if unknown)",
                            },
                            "message": {
                                "type": "string",
                                "description": "Human-readable violation message",
                            },
                        },
                    },
                },
            },
        },
        "rules_output": {
            "description": "Output of the 'rules' command",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "message": {"type": "string"},
                    "severity": {"type": "string"},
                    "backend": {
                        "type": "string",
                        "enum": ["ast-grep", "ruff", "beniget"],
                    },
                },
            },
        },
    }
    json.dump(schema, sys.stdout, indent=2)
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="python-fp-lint",
        description="Functional-programming lint rules for Python",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    sub = parser.add_subparsers(dest="command")

    # --- check ---
    check = sub.add_parser("check", help="Run lint checks on files")
    check.add_argument("files", nargs="+", help="Python files to check")

    # --- rules ---
    sub.add_parser("rules", help="List all available lint rules")

    # --- schema ---
    sub.add_parser("schema", help="Print JSON schema for check/rules output")

    args = parser.parse_args()

    if args.command == "check":
        _run_check(args)
    elif args.command == "rules":
        _run_rules(args)
    elif args.command == "schema":
        _run_schema(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
