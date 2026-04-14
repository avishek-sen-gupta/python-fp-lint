# python_fp_lint/rules_meta.py
"""Rule metadata — reads rule definitions from all backends."""

import os

import yaml


def _rules_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")


def _semgrep_rules_file() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "semgrep-rules.yml")


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
            rules.append({
                "id": data.get("id", fname.removesuffix(".yml")),
                "message": data.get("message", ""),
                "severity": data.get("severity", "warning"),
                "backend": "ast-grep",
            })
        except (yaml.YAMLError, OSError):
            continue
    return rules


def _semgrep_rules() -> list[dict]:
    rules = []
    path = _semgrep_rules_file()
    if not os.path.exists(path):
        return rules
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return rules
    for entry in data.get("rules", []):
        rules.append({
            "id": entry.get("id", "unknown"),
            "message": entry.get("message", ""),
            "severity": entry.get("severity", "WARNING").lower(),
            "backend": "semgrep",
        })
    return rules


def list_rules() -> list[dict]:
    """Return metadata for all available lint rules across all backends."""
    rules = _ast_grep_rules() + _semgrep_rules()
    rules.append({
        "id": "reassignment",
        "message": "Variable reassignment detected — use new bindings instead",
        "severity": "warning",
        "backend": "beniget",
    })
    return rules
