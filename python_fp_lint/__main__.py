# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check file1.py file2.py

Designed for both human use (text output) and LLM agent use (--format json).
"""

import argparse
import json
import subprocess
import sys
import tempfile

from python_fp_lint.hook_check import main as _hook_check_main
from python_fp_lint.lint_gate import ConfigError, LintGate, missing_backends
from python_fp_lint.precommit import evaluate_staged
from python_fp_lint.rules_meta import list_rules


def _split_list(value: str | None) -> list[str] | None:
    """Comma-separated CLI value into a list; None when the flag is unused."""
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_gate(args) -> LintGate:
    return LintGate(
        ruff_select=args.ruff_select or None,
        ast_grep_rules=_split_list(args.ast_grep_rules),
        exclude=_split_list(getattr(args, "exclude", None)),
        config_path=args.config or None,
    )


def _enforce_strict(args) -> None:
    """Exit 2 when --strict is set and a backend is unreachable.

    Without this, a missing `sg` or `ruff` silently disables whole rule
    families -- an invisible pass, which is the wrong default for a gate.
    """
    if not getattr(args, "strict", False):
        return
    missing = missing_backends()
    if missing:
        print(
            f"error: required lint backend(s) not found: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)


def _report(result, fmt: str) -> None:
    """Print a LintResult in the requested format and exit 0/1."""
    violations = result.violations

    if fmt == "json":
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


def _with_config_errors(run, args):
    """Turn a bad --config into a one-line error and exit 2, not a traceback."""
    try:
        run(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


def _run_check(args):
    _enforce_strict(args)
    _report(_build_gate(args).evaluate(args.files, "."), args.format)


def _git_repo_root() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(2)
    return result.stdout.strip()


def _run_precommit(args):
    _enforce_strict(args)
    repo_root = _git_repo_root()
    # Materialize staged blobs outside the repo: ast-grep and Ruff both honour
    # the enclosing tree's ignore rules, and a temp dir inside it may be skipped.
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-staged-") as workdir:
        result = evaluate_staged(
            repo_root=repo_root,
            workdir=workdir,
            gate=_build_gate(args),
            paths=args.files or None,
        )
    _report(result, args.format)


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

    def add_rule_flags(p):
        p.add_argument(
            "--ruff-select",
            default=None,
            help="Comma-separated Ruff rule codes (overrides config.json and default)",
        )
        p.add_argument(
            "--ast-grep-rules",
            default=None,
            help="Comma-separated ast-grep rule IDs to enable (overrides config.json)",
        )
        p.add_argument(
            "--exclude",
            default=None,
            help=(
                "Comma-separated file globs to skip "
                "(overrides the config file's `exclude`)"
            ),
        )
        p.add_argument(
            "--strict",
            action="store_true",
            help="Fail (exit 2) if ast-grep or Ruff is missing instead of skipping",
        )
        p.add_argument(
            "--config",
            required=True,
            metavar="PATH",
            help="Path to the config JSON file (required; no search, no default)",
        )
        return p

    # --- check ---
    check = add_rule_flags(sub.add_parser("check", help="Run lint checks on files"))
    check.add_argument("files", nargs="+", help="Python files to check")

    # --- precommit ---
    precommit = add_rule_flags(
        sub.add_parser(
            "precommit",
            help="Lint the staged content of every staged Python file",
        )
    )
    precommit.add_argument(
        "files",
        nargs="*",
        help="Optional subset of staged files (pre-commit passes these)",
    )

    # --- rules ---
    sub.add_parser("rules", help="List all available lint rules")

    # --- schema ---
    sub.add_parser("schema", help="Print JSON schema for check/rules output")

    # --- hook-check ---
    hook = sub.add_parser(
        "hook-check",
        help="Read a PreToolUse event JSON from stdin and exit 0 (allow) or 2 (block)",
    )
    hook.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Optional config JSON file; omitted means built-in defaults",
    )

    args = parser.parse_args()

    if args.command == "check":
        _with_config_errors(_run_check, args)
    elif args.command == "precommit":
        _with_config_errors(_run_precommit, args)
    elif args.command == "rules":
        _run_rules(args)
    elif args.command == "schema":
        _run_schema(args)
    elif args.command == "hook-check":
        _hook_check_main(args.config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
