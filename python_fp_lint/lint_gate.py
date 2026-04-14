# python_fp_lint/lint_gate.py
"""Lint gates — ast-grep-only and mixed-backend lint checking.

LintGate runs all rules via ast-grep for maximum speed.
MixedLintGate runs Semgrep for pattern rules, plus ast-grep for the two
rules that require tree-sitter-specific features (stopBy, has+kind).
"""

import glob
import json
import os
import shutil
import subprocess

from python_fp_lint.result import LintResult, LintViolation


class LintGate:
    """Pure ast-grep lint checker — runs all 27 rules via ast-grep."""

    def __init__(self, rules_dir: str | None = None):
        self.rules_dir = rules_dir

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = _filter_python_files(changed_files)
        if not py_files:
            return LintResult(passed=True, violations=[])

        rules_dir = self._resolve_rules_dir(project_root)
        if rules_dir is None:
            return LintResult(passed=True, violations=[])

        sg = _find_sg()
        if sg is None:
            return LintResult(
                passed=False,
                violations=[
                    LintViolation(
                        rule="tool-missing",
                        file="",
                        line=0,
                        message="ast-grep (sg) binary not found. Install from: https://ast-grep.github.io/",
                    )
                ],
            )

        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if not os.path.exists(sgconfig):
            return LintResult(passed=True, violations=[])

        violations = _run_sg(sg, rules_dir, py_files)
        return LintResult(passed=len(violations) == 0, violations=violations)

    def _resolve_rules_dir(self, project_root: str) -> str | None:
        return _resolve_rules_dir(self.rules_dir, project_root)


class MixedLintGate:
    """Mixed-backend lint checker — Semgrep rules + ast-grep for tree-sitter-only rules.

    Runs Semgrep for the 26 pattern rules, then ast-grep for no-deep-nesting
    and no-loop-mutation (which require tree-sitter features not expressible
    in Semgrep).
    """

    # ast-grep rules that Semgrep cannot express
    _SG_ONLY_RULES = {"no-deep-nesting", "no-loop-mutation"}

    def __init__(self, rules_dir: str | None = None):
        self.rules_dir = rules_dir

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = _filter_python_files(changed_files)
        if not py_files:
            return LintResult(passed=True, violations=[])

        rules_dir = _resolve_rules_dir(self.rules_dir, project_root)
        if rules_dir is None:
            return LintResult(passed=True, violations=[])

        semgrep = _find_semgrep()
        if semgrep is None:
            return LintResult(
                passed=False,
                violations=[
                    LintViolation(
                        rule="tool-missing",
                        file="",
                        line=0,
                        message="semgrep binary not found. Install with: pip install semgrep",
                    )
                ],
            )

        violations = []

        # Run Semgrep (26 rules)
        semgrep_rules = os.path.join(rules_dir, "semgrep-rules.yml")
        if os.path.exists(semgrep_rules):
            violations.extend(_run_semgrep(semgrep, semgrep_rules, py_files))

        # Run ast-grep for tree-sitter-only rules — optional
        sg = _find_sg()
        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if sg is not None and os.path.exists(sgconfig):
            sg_violations = _run_sg(sg, rules_dir, py_files)
            violations.extend(v for v in sg_violations if v.rule in self._SG_ONLY_RULES)

        return LintResult(passed=len(violations) == 0, violations=violations)

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
        real = os.path.normpath(f)
        if real in seen:
            continue
        seen.add(real)
        if real.endswith(".py") and os.path.exists(real):
            result.append(real)
    return result


def _find_semgrep() -> str | None:
    return shutil.which("semgrep")


def _find_sg() -> str | None:
    return shutil.which("sg") or shutil.which("ast-grep")


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
        if os.path.isdir(candidate) and (
            os.path.exists(os.path.join(candidate, "sgconfig.yml"))
            or os.path.exists(os.path.join(candidate, "semgrep-rules.yml"))
        ):
            return candidate
    return None


def _read_config_rules_dir() -> str | None:
    """Read lint_rules_dir from the plugin config.json."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.json",
    )
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path) as f:
            return json.load(f).get("lint_rules_dir")
    except (json.JSONDecodeError, OSError):
        return None


def _run_semgrep(semgrep_path: str, rules_file: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [semgrep_path, "scan", "--config", rules_file, "--json", "--no-git-ignore"] + files,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if not result.stdout.strip():
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    violations = []
    for entry in data.get("results", []):
        violations.append(LintViolation(
            rule=entry.get("check_id", "unknown").rsplit(".", 1)[-1],
            file=entry.get("path", ""),
            line=entry.get("start", {}).get("line", 0),
            message=entry.get("extra", {}).get("message", ""),
        ))
    return violations


def _run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [sg_path, "scan", "--json", "--config", os.path.join(rules_dir, "sgconfig.yml")] + files,
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
        violations.append(LintViolation(
            rule=entry.get("ruleId", "unknown"),
            file=entry.get("file", ""),
            line=entry.get("range", {}).get("start", {}).get("line", 0) + 1,
            message=entry.get("message", ""),
        ))
    return violations
