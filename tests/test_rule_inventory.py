# tests/test_rule_inventory.py
"""The rule list is written out by hand in several places; they must agree.

The gate's own defaults in lint_gate.py are the source of truth. The `rules`
command, config.example.json and the README each restate them, and a copy that
drifts silently switches a check off for whoever trusts it.
"""

import json
import os
import re

import pytest

from python_fp_lint import lint_gate
from python_fp_lint.rules_meta import _ruff_rules, list_rules

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
RULES_DIR = os.path.join(REPO_ROOT, "python_fp_lint", "rules")


def _read(name: str) -> str:
    with open(os.path.join(REPO_ROOT, name)) as f:
        return f.read()


def _default_ruff_codes() -> list[str]:
    return lint_gate._DEFAULT_RUFF_SELECT.split(",")


def _ast_grep_rule_ids() -> set[str]:
    return {f.removesuffix(".yml") for f in os.listdir(RULES_DIR) if f.endswith(".yml")}


@pytest.fixture(scope="module")
def example_config() -> dict:
    return json.loads(_read("config.example.json"))


@pytest.fixture(scope="module")
def readme() -> str:
    return _read("README.md")


class TestRulesCommand:
    def test_lists_every_default_ruff_code(self):
        assert [r["id"] for r in _ruff_rules()] == _default_ruff_codes()

    def test_lists_every_ast_grep_rule(self):
        listed = {r["id"] for r in list_rules() if r["backend"] == "ast-grep"}
        assert listed == _ast_grep_rule_ids()


class TestExampleConfig:
    def test_ruff_select_is_the_default(self, example_config):
        assert example_config["ruff_select"] == lint_gate._DEFAULT_RUFF_SELECT

    def test_enables_every_ast_grep_rule(self, example_config):
        assert set(example_config["ast_grep_rules"]) == _ast_grep_rule_ids()

    @pytest.mark.parametrize(
        ("key", "default"),
        [
            ("max_complexity", lint_gate._DEFAULT_MAX_COMPLEXITY),
            ("max_statements", lint_gate._DEFAULT_MAX_STATEMENTS),
            ("max_positional_args", lint_gate._DEFAULT_MAX_POSITIONAL_ARGS),
        ],
    )
    def test_ceilings_are_the_defaults(self, example_config, key, default):
        assert example_config[key] == default


class TestReadme:
    def test_example_ruff_select_is_the_default(self, readme):
        assert re.findall(r'"ruff_select": "([^"]+)"', readme) == [
            lint_gate._DEFAULT_RUFF_SELECT
        ]

    def test_every_default_ruff_code_has_a_table_row(self, readme):
        rows = set(re.findall(r"^\| `([A-Z]+[0-9]*)` \|", readme, re.MULTILINE))
        assert set(_default_ruff_codes()) <= rows

    def test_every_ast_grep_rule_has_a_table_row(self, readme):
        rows = set(re.findall(r"^\|[^|]*\| `(no-[a-z-]+)` \|", readme, re.MULTILINE))
        assert rows == _ast_grep_rule_ids()

    def test_stated_ast_grep_counts_are_current(self, readme):
        counts = re.findall(
            r"ast-grep\*\* \((\d+) rules\)"
            r"|ast-grep rules \((\d+)\)"
            r"|(\d+) ast-grep rule files"
            r"|scanning (\d+) rules",
            readme,
        )
        stated = {int(n) for groups in counts for n in groups if n}
        assert stated == {len(_ast_grep_rule_ids())}


class TestDisabledRules:
    def test_are_not_loaded_by_the_gate(self, tmp_path):
        """ast-grep reads ruleDirs recursively, so a disabled rule must live
        outside rules/ entirely -- a subdirectory of it is still scanned."""
        target = tmp_path / "test_vacuous.py"
        target.write_text("def test_nothing():\n    pass\n")
        result = lint_gate.LintGate().evaluate([str(target)], str(tmp_path))
        assert "test-vacuous" not in {v.rule for v in result.violations}

    def test_rules_dir_has_no_nested_rule_files(self):
        nested = [
            os.path.join(root, f)
            for root, _dirs, files in os.walk(RULES_DIR)
            if root != RULES_DIR
            for f in files
            if f.endswith(".yml")
        ]
        assert nested == []
