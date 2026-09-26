# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check file1.py file2.py

Designed for both human use (text output) and LLM agent use (--format json).
"""

import argparse
import json
import subprocess
import sys
import tempfile

from python_fp_lint import baseline as baseline_file
from python_fp_lint import ratchet
from python_fp_lint.hook_check import main as _hook_check_main
from python_fp_lint.lint_gate import (
    BackendError,
    ConfigError,
    LintGate,
    missing_backends,
)
from python_fp_lint.precommit import evaluate_staged, staged_python_files
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
        max_complexity=getattr(args, "max_complexity", None),
        max_statements=getattr(args, "max_statements", None),
        config_path=args.config or None,
        baseline=getattr(args, "baseline", None),
    )


def _resolve_baseline_or_exit(args) -> str:
    """The baseline path in force, or exit 2 -- these commands require one."""
    path = _build_gate(args).resolve_baseline()
    if path is None:
        print(
            "error: no baseline configured; pass --baseline PATH or set "
            '"baseline" in the config file',
            file=sys.stderr,
        )
        sys.exit(2)
    return path


def _require_backends() -> None:
    """Exit 2 when a backend is unreachable.

    The ratchet enforces this unconditionally: a missing backend contributes
    zero violations, which reads as an improvement and would tighten the
    baseline toward zero.
    """
    missing = missing_backends()
    if missing:
        print(
            f"error: required lint backend(s) not found: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)


def _current_total(args) -> int:
    _require_backends()
    result = ratchet.total_violations(_git_repo_root(), _build_gate(args))
    return len(result.violations)


def _run_baseline_update(args):
    path = _resolve_baseline_or_exit(args)
    total = _current_total(args)
    baseline_file.write(path, total)
    if args.format == "json":
        json.dump(
            {"baseline": total, "total": total, "path": path}, sys.stdout, indent=2
        )
        print()
    else:
        print(f"baseline recorded: {total} violation(s) -> {path}")


def _run_baseline_show(args):
    path = _resolve_baseline_or_exit(args)
    recorded = baseline_file.read(path)
    total = _current_total(args)
    if args.format == "json":
        json.dump(
            {"baseline": recorded, "total": total, "path": path}, sys.stdout, indent=2
        )
        print()
    else:
        print(f"baseline: {recorded}\ncurrent:  {total}\npath:     {path}")


def _enforce_strict(args) -> None:
    """Exit 2 when --strict is set and a backend is unreachable.

    Without this, a missing `sg` or `ruff` silently disables whole rule
    families -- an invisible pass, which is the wrong default for a gate.
    """
    if getattr(args, "strict", False):
        _require_backends()


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
    """Turn a bad config, baseline or backend into a one-line error and exit 2."""
    try:
        run(args)
    except (
        ConfigError,
        baseline_file.BaselineError,
        ratchet.RatchetError,
        BackendError,
    ) as exc:
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


_MAX_REPORTED_VIOLATIONS = 50


def _reported_violations(violations, staged: set[str]) -> tuple[list, bool]:
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


def _report_ratchet(verdict, violations, staged: set[str], fmt: str) -> None:
    """Print a ratchet verdict and exit 0 (clean or tightened) or 1 (regression)."""
    reported, is_local = _reported_violations(violations, staged)
    remainder = len(violations) - len(reported)

    if fmt == "json":
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
            "violations": [
                {"rule": v.rule, "file": v.file, "line": v.line, "message": v.message}
                for v in reported
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    elif verdict.regressed:
        print(f"ratchet: {verdict.recorded} → {verdict.total} (+{verdict.delta})")
        for v in reported:
            loc = f"{v.file}:{v.line}" if v.line else v.file
            print(f"  [{v.rule}] {loc} — {v.message}")
        if not remainder:
            pass
        elif is_local:
            print(
                f"\n{remainder} further violation(s) in the rest of the repo, "
                "in files you did not stage."
            )
        else:
            print(f"\n… and {remainder} more (run `check` for the full list)")
    elif verdict.tightened:
        print(f"ratchet: {verdict.recorded} → {verdict.total} ({verdict.delta})")
    elif verdict.dropped:
        # --no-tighten: the only way to reach a fall that was not recorded.
        # Silence here is how a baseline drifts above reality forever.
        print(
            f"ratchet: {verdict.recorded} → {verdict.total} ({verdict.delta}) "
            "— not tightened (--no-tighten); run `baseline update` to record it"
        )

    sys.exit(1 if verdict.regressed else 0)


def _run_precommit(args):
    # Must run before anything reads --config: resolve_baseline() eagerly opens
    # and parses the config file, which would reorder the two failure modes
    # for `--strict` with both a missing backend and a bad --config, breaking
    # the no-baseline path's "byte-for-byte unchanged" guarantee.
    _enforce_strict(args)
    repo_root = _git_repo_root()
    gate = _build_gate(args)
    baseline_path = gate.resolve_baseline()
    if baseline_path is None:
        _run_precommit_staged(args, gate, repo_root)
    else:
        _run_precommit_ratchet(args, gate, repo_root, baseline_path)


def _run_precommit_staged(args, gate: LintGate, repo_root: str) -> None:
    """The original gate: every violation in a staged file blocks the commit."""
    # Materialize staged blobs outside the repo: ast-grep and Ruff both honour
    # the enclosing tree's ignore rules, and a temp dir inside it may be skipped.
    with tempfile.TemporaryDirectory(prefix="python-fp-lint-staged-") as workdir:
        result = evaluate_staged(
            repo_root=repo_root,
            workdir=workdir,
            gate=gate,
            paths=args.files or None,
        )
    _report(result, args.format)


def _run_precommit_ratchet(
    args, gate: LintGate, repo_root: str, baseline_path: str
) -> None:
    """The ratchet: the whole-repo total may fall and may not rise.

    This replaces the staged check rather than adding to it. Leaving the
    staged check on would make a dirty legacy repo uncommittable, which is
    the situation the ratchet exists to escape.
    """
    _require_backends()
    result = ratchet.total_violations(repo_root, gate)
    verdict = ratchet.apply(
        repo_root,
        baseline_path,
        total=len(result.violations),
        tighten=not args.no_tighten,
    )
    _report_ratchet(
        verdict, result.violations, set(staged_python_files(repo_root)), args.format
    )


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


_VIOLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "rule": {"type": "string", "description": "Rule ID that was violated"},
        "file": {"type": "string", "description": "Path to the file"},
        "line": {
            "type": "integer",
            "description": "Line number (1-based, 0 if unknown)",
        },
        "message": {
            "type": "string",
            "description": "Human-readable violation message",
        },
    },
}


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
                    "description": (
                        "Number of violations; always equal to the length of "
                        "'violations' for this command"
                    ),
                },
                "violations": {"type": "array", "items": _VIOLATION_SCHEMA},
            },
        },
        "precommit_ratchet_output": {
            "description": (
                "Output of 'precommit' when a baseline is configured "
                "(ratchet mode). Without one, 'precommit' emits check_output."
            ),
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": (
                        "True unless the repo-wide total rose above the "
                        "recorded baseline"
                    ),
                },
                "violation_count": {
                    "type": "integer",
                    "description": (
                        "Violations in the whole repo -- the number the "
                        "ratchet compares against the baseline. NOT the "
                        "length of 'violations'."
                    ),
                },
                "reported_violation_count": {
                    "type": "integer",
                    "description": (
                        "Length of 'violations': the staged files' violations "
                        "when anything is staged, otherwise the whole list "
                        "capped at 50"
                    ),
                },
                "ratchet": {
                    "type": "object",
                    "properties": {
                        "baseline": {
                            "type": "integer",
                            "description": "The total recorded in the baseline file",
                        },
                        "total": {
                            "type": "integer",
                            "description": "The repo-wide total this run measured",
                        },
                        "tightened": {
                            "type": "boolean",
                            "description": (
                                "True when the total fell and the baseline "
                                "file was rewritten and staged"
                            ),
                        },
                    },
                },
                "violations": {
                    "type": "array",
                    "description": (
                        "The reported subset, not the whole repo; "
                        "'violation_count' is the whole repo"
                    ),
                    "items": _VIOLATION_SCHEMA,
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
            "--max-complexity",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Maximum cyclomatic complexity per function, reported as Ruff "
                "C901 (overrides the config file's `max_complexity`)"
            ),
        )
        p.add_argument(
            "--max-statements",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Maximum statements per function, reported as Ruff PLR0915 "
                "(overrides the config file's `max_statements`)"
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

    def add_baseline_flag(p):
        """Only for the commands a baseline means something to.

        On `check` it would be accepted and silently ignored, which reads as
        support for a ratchet mode `check` does not have.
        """
        p.add_argument(
            "--baseline",
            default=None,
            metavar="PATH",
            help=(
                "Path to the ratchet baseline file "
                "(overrides the config file's `baseline`)"
            ),
        )
        return p

    # --- check ---
    check = add_rule_flags(sub.add_parser("check", help="Run lint checks on files"))
    check.add_argument("files", nargs="+", help="Python files to check")

    # --- precommit ---
    precommit = add_baseline_flag(
        add_rule_flags(
            sub.add_parser(
                "precommit",
                help="Lint the staged content of every staged Python file",
            )
        )
    )
    precommit.add_argument(
        "files",
        nargs="*",
        help="Optional subset of staged files (pre-commit passes these)",
    )
    precommit.add_argument(
        "--no-tighten",
        action="store_true",
        help=(
            "Never rewrite or stage the baseline; a fallen total passes with a "
            "warning. Use this in CI, where nothing is staged."
        ),
    )

    # --- rules ---
    sub.add_parser("rules", help="List all available lint rules")

    # --- baseline ---
    baseline_cmd = sub.add_parser(
        "baseline", help="Record or inspect the ratchet's violation total"
    )
    baseline_sub = baseline_cmd.add_subparsers(dest="baseline_command", required=True)
    add_baseline_flag(
        add_rule_flags(
            baseline_sub.add_parser(
                "update", help="Lint the index and record the total"
            )
        )
    )
    add_baseline_flag(
        add_rule_flags(
            baseline_sub.add_parser(
                "show", help="Print the recorded and current totals"
            )
        )
    )

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
    elif args.command == "baseline":
        run = (
            _run_baseline_update
            if args.baseline_command == "update"
            else _run_baseline_show
        )
        _with_config_errors(run, args)
    elif args.command == "schema":
        _run_schema(args)
    elif args.command == "hook-check":
        _hook_check_main(args.config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
