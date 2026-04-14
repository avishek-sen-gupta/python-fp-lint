# python_fp_lint/lint_gate.py
"""LintGate — dual-backend lint checking.

Runs Semgrep for the majority of lint rules, then ast-grep for the
rules that require tree-sitter-specific features (stopBy, has+kind).
Results are merged into a single violation list.
"""

import json
import os
import shutil
import subprocess

from python_fp_lint.result import LintResult, LintViolation


class LintGate:
    """Lint checker that runs Semgrep and ast-grep rules on Python files."""

    def __init__(self, rules_dir: str | None = None):
        self.rules_dir = rules_dir

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = self._filter_python_files(changed_files)
        if not py_files:
            return LintResult(passed=True, violations=[])

        rules_dir = self._resolve_rules_dir(project_root)
        if rules_dir is None:
            return LintResult(passed=True, violations=[])

        # Semgrep is required
        semgrep = self._find_semgrep()
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
            violations.extend(self._run_semgrep(semgrep, semgrep_rules, py_files))

        # Run ast-grep (2 remaining rules) — optional
        sg = self._find_sg()
        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if sg is not None and os.path.exists(sgconfig):
            violations.extend(self._run_sg(sg, rules_dir, py_files))

        return LintResult(passed=len(violations) == 0, violations=violations)

    @staticmethod
    def _filter_python_files(files: list[str]) -> list[str]:
        """Filter to existing, unique .py files."""
        seen = set()
        result = []
        for f in files:
            if f in seen:
                continue
            seen.add(f)
            if f.endswith(".py") and os.path.exists(f):
                result.append(f)
        return result

    @staticmethod
    def _find_semgrep() -> str | None:
        return shutil.which("semgrep")

    @staticmethod
    def _find_sg() -> str | None:
        return shutil.which("sg") or shutil.which("ast-grep")

    def _resolve_rules_dir(self, project_root: str) -> str | None:
        """Find the lint rules directory.

        Searches in order: explicit rules_dir, package-local (next to this file),
        project-local scripts/lint/, then lint_rules_dir from config.json.
        """
        if self.rules_dir:
            return self.rules_dir
        # Package-local: rule files live alongside this module
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            pkg_dir,
            os.path.join(project_root, "scripts", "lint"),
        ]
        config_dir = self._read_config_rules_dir()
        if config_dir:
            candidates.append(config_dir)
        for candidate in candidates:
            if os.path.isdir(candidate) and (
                os.path.exists(os.path.join(candidate, "sgconfig.yml"))
                or os.path.exists(os.path.join(candidate, "semgrep-rules.yml"))
            ):
                return candidate
        return None

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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
