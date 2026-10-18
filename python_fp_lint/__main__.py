# python_fp_lint/__main__.py
"""CLI entry point: python -m python_fp_lint check file1.py file2.py

Designed for both human use (text output) and LLM agent use (--format json).
"""

import argparse
import json
import logging
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
    _validate_ceiling,
    missing_backends,
)
from python_fp_lint.output import OutputFormat, configure_cli_logging, emit
from python_fp_lint.precommit import evaluate_staged, staged_python_files
from python_fp_lint.reports import CheckReport, RatchetReport
from python_fp_lint.rules_meta import list_rules
from python_fp_lint.settings import (
    UNSET,
    ConfigLayer,
    Unset,
    layer_from_config_file,
    resolve_settings,
)

# Not __name__: run as `python -m python_fp_lint` that is "__main__", outside
# the package logger configure_cli_logging() sets up. Configured at import,
# not in main(), so the commands' error lines reach stderr however they are
# entered; this module is the CLI and is never imported as a library.
log = logging.getLogger("python_fp_lint.cli")
configure_cli_logging()


def _split_list(value: str) -> list[str]:
    """Comma-separated CLI value into a list; empty when the flag is unused."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _cli_layer(args) -> ConfigLayer:
    """The command line as a settings layer. A flag the user did not pass is
    absent from `args` (argparse.SUPPRESS), so it reads as UNSET here."""
    return ConfigLayer(
        ruff_select=getattr(args, "ruff_select", "") or UNSET,
        ast_grep_rules=tuple(_split_list(getattr(args, "ast_grep_rules", ""))),
        exclude=tuple(_split_list(getattr(args, "exclude", ""))),
        max_complexity=_cli_ceiling(args, "max_complexity"),
        max_statements=_cli_ceiling(args, "max_statements"),
        max_positional_args=_cli_ceiling(args, "max_positional_args"),
        baseline=getattr(args, "baseline", UNSET),
    )


def _cli_ceiling(args, name: str) -> int | Unset:
    value = getattr(args, name, UNSET)
    return UNSET if value is UNSET else _validate_ceiling(name, value)


def _build_gate(args) -> LintGate:
    return LintGate(
        settings=resolve_settings(
            _cli_layer(args), layer_from_config_file(args.config), "."
        )
    )


def _baseline_path(args) -> str | Unset:
    """The baseline in force: the command line's, else the config file's."""
    cli = _cli_layer(args).baseline
    return cli if cli is not UNSET else layer_from_config_file(args.config).baseline


def _resolve_baseline_or_exit(args) -> str:
    """The baseline path in force, or exit 2 -- these commands require one."""
    path = _baseline_path(args)
    if path is UNSET:
        log.error(
            "error: no baseline configured; pass --baseline PATH or set "
            '"baseline" in the config file'
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
        log.error(f"error: required lint backend(s) not found: {', '.join(missing)}")
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
        emit(json.dumps({"baseline": total, "total": total, "path": path}, indent=2))
    else:
        emit(f"baseline recorded: {total} violation(s) -> {path}")


def _run_baseline_show(args):
    path = _resolve_baseline_or_exit(args)
    recorded = baseline_file.read(path)
    total = _current_total(args)
    if args.format == "json":
        emit(json.dumps({"baseline": recorded, "total": total, "path": path}, indent=2))
    else:
        emit(f"baseline: {recorded}\ncurrent:  {total}\npath:     {path}")


def _enforce_strict(args) -> None:
    """Exit 2 when --strict is set and a backend is unreachable.

    Without this, a missing `sg` or `ruff` silently disables whole rule
    families -- an invisible pass, which is the wrong default for a gate.
    """
    if getattr(args, "strict", False):
        _require_backends()


def _report(result, fmt: str) -> None:
    """Print a LintResult in the requested format and exit 0/1."""
    _emit_report(CheckReport(result), fmt)


def _report_ratchet(verdict, violations, staged: set[str], fmt: str) -> None:
    """Print a ratchet verdict and exit 0 (clean or tightened) or 1 (regression)."""
    _emit_report(RatchetReport(verdict, violations, frozenset(staged)), fmt)


def _emit_report(report, fmt: str) -> None:
    text = report.render(OutputFormat[fmt.upper()])
    if text:
        emit(text, report.stream)
    sys.exit(report.exit_code)


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
        log.error(f"error: {exc}")
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
        log.error("error: not inside a git repository")
        sys.exit(2)
    return result.stdout.strip()


def _run_precommit(args):
    # Must run before anything reads --config: building the gate opens and
    # parses the config file, which would reorder the two failure modes
    # for `--strict` with both a missing backend and a bad --config, breaking
    # the no-baseline path's "byte-for-byte unchanged" guarantee.
    _enforce_strict(args)
    repo_root = _git_repo_root()
    gate = _build_gate(args)
    baseline_path = _baseline_path(args)
    if baseline_path is UNSET:
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
            paths=args.files,
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
    emit(
        json.dumps(rules, indent=2)
        if args.format == "json"
        else "\n".join(
            f"  [{r['backend']:8s}] {r['id']}\n             {r['message']}"
            for r in rules
        )
    )


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
    emit(json.dumps(schema, indent=2))


def _add_rule_flags(p):
    p.add_argument(
        "--ruff-select",
        default=argparse.SUPPRESS,
        help="Comma-separated Ruff rule codes (overrides config.json and default)",
    )
    p.add_argument(
        "--ast-grep-rules",
        default="",
        help="Comma-separated ast-grep rule IDs to enable (overrides config.json)",
    )
    p.add_argument(
        "--exclude",
        default="",
        help=(
            "Comma-separated file globs to skip "
            "(overrides the config file's `exclude`)"
        ),
    )
    p.add_argument(
        "--max-complexity",
        type=int,
        default=argparse.SUPPRESS,
        metavar="N",
        help=(
            "Maximum cyclomatic complexity per function, reported as Ruff "
            "C901 (overrides the config file's `max_complexity`)"
        ),
    )
    p.add_argument(
        "--max-statements",
        type=int,
        default=argparse.SUPPRESS,
        metavar="N",
        help=(
            "Maximum statements per function, reported as Ruff PLR0915 "
            "(overrides the config file's `max_statements`)"
        ),
    )
    p.add_argument(
        "--max-positional-args",
        type=int,
        default=argparse.SUPPRESS,
        metavar="N",
        help=(
            "Maximum positional parameters per function, reported as Ruff "
            "PLR0917 (overrides the config file's `max_positional_args`)"
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


def _add_baseline_flag(p):
    """Only for the commands a baseline means something to.

    On `check` it would be accepted and silently ignored, which reads as
    support for a ratchet mode `check` does not have.
    """
    p.add_argument(
        "--baseline",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help=(
            "Path to the ratchet baseline file "
            "(overrides the config file's `baseline`)"
        ),
    )
    return p


def _add_check(sub) -> None:
    check = _add_rule_flags(sub.add_parser("check", help="Run lint checks on files"))
    check.add_argument("files", nargs="+", help="Python files to check")


def _add_precommit(sub) -> None:
    precommit = _add_baseline_flag(
        _add_rule_flags(
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


def _add_baseline(sub) -> None:
    baseline_cmd = sub.add_parser(
        "baseline", help="Record or inspect the ratchet's violation total"
    )
    baseline_sub = baseline_cmd.add_subparsers(dest="baseline_command", required=True)
    _add_baseline_flag(
        _add_rule_flags(
            baseline_sub.add_parser(
                "update", help="Lint the index and record the total"
            )
        )
    )
    _add_baseline_flag(
        _add_rule_flags(
            baseline_sub.add_parser(
                "show", help="Print the recorded and current totals"
            )
        )
    )


def _add_hook_check(sub) -> None:
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


def _build_parser() -> argparse.ArgumentParser:
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
    # Subcommands in the order --help lists them.
    _add_check(sub)
    _add_precommit(sub)
    sub.add_parser("rules", help="List all available lint rules")
    _add_baseline(sub)
    sub.add_parser("schema", help="Print JSON schema for check/rules output")
    _add_hook_check(sub)
    return parser


def _run_baseline(args) -> None:
    run = (
        _run_baseline_update
        if args.baseline_command == "update"
        else _run_baseline_show
    )
    _with_config_errors(run, args)


# Each subcommand's entry point, by the name argparse stores in args.command.
_COMMANDS = {
    "check": lambda args: _with_config_errors(_run_check, args),
    "precommit": lambda args: _with_config_errors(_run_precommit, args),
    "rules": _run_rules,
    "baseline": _run_baseline,
    "schema": _run_schema,
    "hook-check": lambda args: _hook_check_main(args.config),
}


def main():
    parser = _build_parser()
    args = parser.parse_args()
    if args.command not in _COMMANDS:
        parser.print_help()
        sys.exit(1)
    _COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
