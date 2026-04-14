# python_fp_lint/rules_meta.py
"""Rule metadata — reads rule definitions from all backends."""

import os

import yaml


def _rules_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")


def _ast_grep_rules() -> list[dict]:
    rules = []
    rdir = _rules_dir()
    if not os.path.isdir(rdir):
        return rules
    for fname in sorted(os.listdir(rdir)):
        if not fname.endswith(".yml") or fname == "sgconfig.yml":
            continue
        path = os.path.join(rdir, fname)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            rules.append(
                {
                    "id": data.get("id", fname.removesuffix(".yml")),
                    "message": data.get("message", ""),
                    "severity": data.get("severity", "warning"),
                    "backend": "ast-grep",
                }
            )
        except (yaml.YAMLError, OSError):
            continue
    return rules


def _ruff_rules() -> list[dict]:
    """Return metadata for Ruff rules selected in LintGate._RUFF_SELECT."""
    # Ruff rule codes selected in LintGate: E, F, W, I, B, UP, SIM, RUF, BLE, T20, TID252, C901
    return [
        {
            "id": "E",
            "message": "pycodestyle (PEP 8) error checks",
            "severity": "error",
            "backend": "ruff",
        },
        {
            "id": "F",
            "message": "Pyflakes checks",
            "severity": "error",
            "backend": "ruff",
        },
        {
            "id": "W",
            "message": "pycodestyle (PEP 8) warning checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "I",
            "message": "isort import sorting checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "B",
            "message": "flake8-bugbear checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "UP",
            "message": "pyupgrade checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "SIM",
            "message": "flake8-simplify checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "RUF",
            "message": "Ruff-specific checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "BLE",
            "message": "flake8-blind-except checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "T20",
            "message": "flake8-print checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "TID252",
            "message": "flake8-tidy-imports checks",
            "severity": "warning",
            "backend": "ruff",
        },
        {
            "id": "C901",
            "message": "McCabe complexity checks",
            "severity": "warning",
            "backend": "ruff",
        },
    ]


def list_rules() -> list[dict]:
    """Return metadata for all available lint rules across all backends."""
    rules = _ast_grep_rules() + _ruff_rules()
    rules.append(
        {
            "id": "reassignment",
            "message": "Variable reassignment detected — use new bindings instead",
            "severity": "warning",
            "backend": "beniget",
        }
    )
    return rules
