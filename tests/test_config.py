# tests/test_config.py
"""Config is explicit: named on the command line, never searched for."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from python_fp_lint import lint_gate
from python_fp_lint.lint_gate import ConfigError, LintGate, _read_config

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _run(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "python_fp_lint", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


def _write_config(tmp_path, **values):
    path = tmp_path / "fp.json"
    path.write_text(json.dumps(values))
    return str(path)


class TestReadConfig:
    def test_no_path_means_no_config(self):
        assert _read_config("ruff_select", None) is None

    def test_reads_named_file(self, tmp_path):
        path = _write_config(tmp_path, ruff_select="E,F")
        assert _read_config("ruff_select", path) == "E,F"

    def test_absent_key_is_none(self, tmp_path):
        path = _write_config(tmp_path, ruff_select="E,F")
        assert _read_config("ast_grep_rules", path) is None

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            _read_config("ruff_select", str(tmp_path / "nope.json"))

    def test_malformed_file_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(ConfigError, match="cannot read"):
            _read_config("ruff_select", str(path))

    def test_no_config_json_is_read_from_the_package_directory(self, tmp_path):
        """Regression guard: discovery relative to the package is gone.

        A config.json sitting next to the installed package must have no
        effect -- only the named file counts.
        """
        gate = LintGate(config_path=None)
        assert gate._config("ruff_select") is None


class TestConfigAppliedByGate:
    def test_ruff_select_from_config_narrows_rules(self, tmp_path):
        target = tmp_path / "noisy.py"
        target.write_text("import os\nprint('hi')\n")
        # T20 only: the unused import (F401) must not be reported.
        path = _write_config(tmp_path, ruff_select="T20")
        result = LintGate(config_path=path).evaluate([str(target)], str(tmp_path))
        rules = {v.rule for v in result.violations}
        assert "T201" in rules
        assert "F401" not in rules

    def test_ast_grep_rules_from_config_narrows_rules(self, tmp_path):
        target = tmp_path / "mut.py"
        target.write_text("xs = []\nxs.append(1)\nd = {}\nd['k'] = 1\n")
        path = _write_config(tmp_path, ast_grep_rules=["no-list-append"])
        result = LintGate(config_path=path).evaluate([str(target)], str(tmp_path))
        rules = {v.rule for v in result.violations}
        assert "no-list-append" in rules
        assert "no-subscript-mutation" not in rules

    def test_constructor_argument_beats_config(self, tmp_path):
        target = tmp_path / "noisy.py"
        target.write_text("import os\nprint('hi')\n")
        path = _write_config(tmp_path, ruff_select="T20")
        gate = LintGate(ruff_select="F", config_path=path)
        rules = {v.rule for v in gate.evaluate([str(target)], str(tmp_path)).violations}
        assert "F401" in rules
        assert "T201" not in rules


class TestConfigRequiredOnCLI:
    def test_check_without_config_is_a_usage_error(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        result = _run("check", str(target))
        assert result.returncode == 2
        assert "--config" in result.stderr

    def test_precommit_without_config_is_a_usage_error(self):
        result = _run("precommit")
        assert result.returncode == 2
        assert "--config" in result.stderr

    def test_missing_config_file_exits_two_without_traceback(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        result = _run("check", "--config", str(tmp_path / "nope.json"), str(target))
        assert result.returncode == 2
        assert "config file not found" in result.stderr
        assert "Traceback" not in result.stderr

    def test_malformed_config_file_exits_two_without_traceback(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = _run("check", "--config", str(bad), str(target))
        assert result.returncode == 2
        assert "cannot read config file" in result.stderr
        assert "Traceback" not in result.stderr

    def test_rules_and_schema_need_no_config(self):
        assert _run("rules").returncode == 0
        assert _run("schema").returncode == 0

    def test_shipped_example_config_is_accepted(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        result = _run(
            "check",
            "--config",
            os.path.join(REPO_ROOT, "config.example.json"),
            str(target),
        )
        assert result.returncode == 0, result.stderr


class TestRelativeRulesDir:
    """A relative lint_rules_dir is relative to the config file, not to cwd.

    The packaged rules dir always wins as the first candidate, so these assert
    on the candidate the gate hands to the resolver.
    """

    @staticmethod
    def _captured_config_dir(monkeypatch, gate, project_root):
        seen = []
        monkeypatch.setattr(
            "python_fp_lint.lint_gate._resolve_rules_dir",
            lambda _explicit, _root, config_dir=None: seen.append(config_dir),
        )
        gate._resolve_rules_dir(project_root)
        return seen[0]

    def test_relative_path_is_joined_to_the_config_directory(
        self, tmp_path, monkeypatch
    ):
        cfg_dir = tmp_path / "cfgdir"
        cfg_dir.mkdir()
        path = cfg_dir / "fp.json"
        path.write_text(json.dumps({"lint_rules_dir": "myrules"}))
        captured = self._captured_config_dir(
            monkeypatch, LintGate(config_path=str(path)), str(tmp_path)
        )
        assert captured == str(cfg_dir / "myrules")

    def test_absolute_path_is_left_alone(self, tmp_path, monkeypatch):
        path = tmp_path / "fp.json"
        path.write_text(json.dumps({"lint_rules_dir": "/opt/rules"}))
        captured = self._captured_config_dir(
            monkeypatch, LintGate(config_path=str(path)), str(tmp_path)
        )
        assert captured == "/opt/rules"

    def test_no_config_yields_no_candidate(self, tmp_path, monkeypatch):
        captured = self._captured_config_dir(
            monkeypatch, LintGate(config_path=None), str(tmp_path)
        )
        assert captured is None


class TestConfiguredRulesDirWins:
    """A rules dir named in the config outranks the copy inside the package."""

    @staticmethod
    def _install_rules(dest):
        os.makedirs(os.path.join(dest, "rules"), exist_ok=True)
        with open(os.path.join(dest, "sgconfig.yml"), "w") as f:
            f.write("ruleDirs:\n  - rules\n")
        shutil.copy(
            os.path.join(REPO_ROOT, "python_fp_lint", "rules", "no-list-append.yml"),
            os.path.join(dest, "rules", "no-list-append.yml"),
        )
        return dest

    def test_config_rules_dir_beats_package_copy(self, tmp_path):
        rules = self._install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")
        assert LintGate(config_path=path)._resolve_rules_dir(str(tmp_path)) == rules

    def test_configured_dir_is_scanned_in_place(self, tmp_path, monkeypatch):
        """No copy to a cache: the consumer put the rules where they want them."""
        rules = self._install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")
        copied = []
        monkeypatch.setattr(
            lint_gate,
            "_materialize_rules_dir",
            lambda src, root: copied.append(src) or src,
        )
        target = tmp_path / "m.py"
        target.write_text("xs = []\nxs.append(1)\n")

        result = LintGate(config_path=path).evaluate([str(target)], str(tmp_path))

        assert copied == [], "configured rules dir must not be materialized"
        assert any(v.rule == "no-list-append" for v in result.violations)
        assert os.path.isdir(rules)

    def test_deleting_a_configured_rule_disables_it(self, tmp_path):
        """Proves the configured dir -- not the package copy -- is in play."""
        rules = self._install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")
        target = tmp_path / "m.py"
        target.write_text("xs = []\nxs.append(1)\n")
        os.unlink(os.path.join(rules, "rules", "no-list-append.yml"))

        result = LintGate(config_path=path).evaluate([str(target)], str(tmp_path))

        assert not any(v.rule == "no-list-append" for v in result.violations)
