# python_fp_lint/lint_gate.py
"""Unified LintGate — runs ast-grep + Ruff + beniget in sequence."""

import glob
import json
import os
import shutil
import subprocess

from python_fp_lint.reassignment_gate import ReassignmentGate
from python_fp_lint.result import LintResult, LintViolation

# Ruff rule selection — batteries-included + FP-specific
_DEFAULT_RUFF_SELECT = "E,F,W,I,B,UP,SIM,RUF,BLE,T20,TID252,C901"


class LintGate:
    """Unified lint gate — runs ast-grep, Ruff, and beniget reassignment detection."""

    def __init__(
        self,
        rules_dir: str | None = None,
        ruff_select: str | None = None,
        ast_grep_rules: list[str] | None = None,
    ):
        self.rules_dir = rules_dir
        self.ruff_select = ruff_select
        self.ast_grep_rules = ast_grep_rules

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = _filter_python_files(changed_files)
        if not py_files:
            return LintResult(passed=True, violations=[])

        violations = []
        violations.extend(self._run_ast_grep(py_files, project_root))
        violations.extend(self._run_ruff(py_files))
        violations.extend(self._run_reassignment(py_files, project_root))

        return LintResult(passed=len(violations) == 0, violations=violations)

    def _resolve_ast_grep_rules(self) -> list[str] | None:
        if self.ast_grep_rules is not None:
            return self.ast_grep_rules
        config_val = _read_config("ast_grep_rules")
        if config_val and isinstance(config_val, list):
            return config_val
        return None

    def _run_ast_grep(self, files: list[str], project_root: str) -> list[LintViolation]:
        rules_dir = self._resolve_rules_dir(project_root)
        if rules_dir is None:
            return []

        sg = _find_sg()
        if sg is None:
            return []

        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if not os.path.exists(sgconfig):
            return []

        violations = _run_sg(sg, rules_dir, files)
        allowed = self._resolve_ast_grep_rules()
        if allowed is not None:
            violations = [v for v in violations if v.rule in allowed]
        return violations

    def _resolve_ruff_select(self) -> str:
        if self.ruff_select:
            return self.ruff_select
        config_select = _read_config_ruff_select()
        if config_select:
            return config_select
        return _DEFAULT_RUFF_SELECT

    def _run_ruff(self, files: list[str]) -> list[LintViolation]:
        ruff = _find_ruff()
        if ruff is None:
            return []
        return _run_ruff(ruff, files, self._resolve_ruff_select())

    def _run_reassignment(
        self, files: list[str], project_root: str
    ) -> list[LintViolation]:
        result = ReassignmentGate().evaluate(files, project_root)
        return result.violations

    def _resolve_rules_dir(self, project_root: str) -> str | None:
        return _resolve_rules_dir(self.rules_dir, project_root)


# --- shared helpers ---


def _expand_paths(paths: list[str]) -> list[str]:
    """Expand directories, globs, and plain files into a flat list of paths."""
    expanded = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    expanded.append(os.path.join(root, f))
        elif any(c in p for c in ("*", "?", "[")):
            expanded.extend(glob.glob(p, recursive=True))
        else:
            expanded.append(p)
    return expanded


def _filter_python_files(files: list[str]) -> list[str]:
    """Expand dirs/globs, then filter to existing, unique .py files."""
    seen = set()
    result = []
    for f in _expand_paths(files):
        real = os.path.abspath(f)
        if real in seen:
            continue
        seen.add(real)
        if real.endswith(".py") and os.path.exists(real):
            result.append(real)
    return result


def _find_sg() -> str | None:
    return shutil.which("sg") or shutil.which("ast-grep")


def _find_ruff() -> str | None:
    return shutil.which("ruff")


def _resolve_rules_dir(explicit_dir: str | None, project_root: str) -> str | None:
    """Find the lint rules directory.

    Searches in order: explicit rules_dir, package-local (next to this file),
    project-local scripts/lint/, then lint_rules_dir from config.json.
    """
    if explicit_dir:
        return explicit_dir
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        pkg_dir,
        os.path.join(project_root, "scripts", "lint"),
    ]
    config_dir = _read_config_rules_dir()
    if config_dir:
        candidates.append(config_dir)
    for candidate in candidates:
        if os.path.isdir(candidate) and os.path.exists(
            os.path.join(candidate, "sgconfig.yml")
        ):
            return candidate
    return None


def _read_config(key: str) -> str | None:
    """Read a value from the plugin config.json."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.json",
    )
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path) as f:
            return json.load(f).get(key)
    except (json.JSONDecodeError, OSError):
        return None


def _read_config_rules_dir() -> str | None:
    return _read_config("lint_rules_dir")


def _read_config_ruff_select() -> str | None:
    return _read_config("ruff_select")


def _run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                sg_path,
                "scan",
                "--json",
                "--config",
                os.path.join(rules_dir, "sgconfig.yml"),
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=rules_dir,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        entries = []
        for line in result.stdout.strip().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    violations = []
    for entry in entries:
        violations.append(
            LintViolation(
                rule=entry.get("ruleId", "unknown"),
                file=entry.get("file", ""),
                line=entry.get("range", {}).get("start", {}).get("line", 0) + 1,
                message=entry.get("message", ""),
            )
        )
    return violations


def _run_ruff(ruff_path: str, files: list[str], select: str) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                ruff_path,
                "check",
                "--output-format",
                "json",
                "--select",
                select,
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    violations = []
    for entry in entries:
        violations.append(
            LintViolation(
                rule=entry.get("code", "unknown"),
                file=entry.get("filename", ""),
                line=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
            )
        )
    return violations
