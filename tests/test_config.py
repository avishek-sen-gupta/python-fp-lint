# tests/test_config.py
"""Config is explicit: named on the command line, never searched for."""

import json
import os
import shutil
import subprocess
import sys

from python_fp_lint import lint_gate
from python_fp_lint.lint_gate import (
    LintGate,
)
from python_fp_lint.settings import (
    ConfigLayer,
    layer_from_config_file,
    load_settings,
    resolve_settings,
)

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


class TestConfigAppliedByGate:
    def test_ruff_select_from_config_narrows_rules(self, tmp_path):
        target = tmp_path / "noisy.py"
        target.write_text("import os\nprint('hi')\n")
        # T20 only: the unused import (F401) must not be reported.
        path = _write_config(tmp_path, ruff_select="T20")
        result = LintGate(settings=load_settings(path)).evaluate(
            [str(target)], str(tmp_path)
        )
        rules = [v.rule for v in result.violations]
        assert rules.count("T201") == 1
        assert "F401" not in rules

    def test_ast_grep_rules_from_config_narrows_rules(self, tmp_path):
        target = tmp_path / "mut.py"
        target.write_text("xs = []\nxs.append(1)\nd = {}\nd['k'] = 1\n")
        path = _write_config(tmp_path, ast_grep_rules=["no-list-append"])
        result = LintGate(settings=load_settings(path)).evaluate(
            [str(target)], str(tmp_path)
        )
        rules = [v.rule for v in result.violations]
        assert rules.count("no-list-append") == 1
        assert "no-subscript-mutation" not in rules

    def test_constructor_argument_beats_config(self, tmp_path):
        target = tmp_path / "noisy.py"
        target.write_text("import os\nprint('hi')\n")
        path = _write_config(tmp_path, ruff_select="T20")
        gate = LintGate(
            settings=resolve_settings(
                ConfigLayer(ruff_select="F"), layer_from_config_file(path), "."
            )
        )
        rules = [v.rule for v in gate.evaluate([str(target)], str(tmp_path)).violations]
        assert rules.count("F401") == 1
        assert "T201" not in rules


class TestConfigRequiredOnCLI:
    def test_check_without_config_is_a_usage_error(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        result = _run("check", str(target))
        assert result.returncode == 2
        assert result.stderr.splitlines()[-1] == (
            "python-fp-lint check: error: the following arguments are required: --config"
        )

    def test_precommit_without_config_is_a_usage_error(self):
        result = _run("precommit")
        assert result.returncode == 2
        assert result.stderr.splitlines()[-1] == (
            "python-fp-lint precommit: error: "
            "the following arguments are required: --config"
        )

    def test_missing_config_file_exits_two_without_traceback(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        result = _run("check", "--config", str(tmp_path / "nope.json"), str(target))
        assert result.returncode == 2
        assert result.stderr.count("config file not found") == 1
        assert "Traceback" not in result.stderr

    def test_malformed_config_file_exits_two_without_traceback(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n")
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = _run("check", "--config", str(bad), str(target))
        assert result.returncode == 2
        assert result.stderr.count("cannot read config file") == 1
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


def _install_rules(dest):
    os.makedirs(os.path.join(dest, "rules"), exist_ok=True)
    with open(os.path.join(dest, "sgconfig.yml"), "w") as f:
        f.write("ruleDirs:\n  - rules\n")
    shutil.copy(
        os.path.join(REPO_ROOT, "python_fp_lint", "rules", "no-list-append.yml"),
        os.path.join(dest, "rules", "no-list-append.yml"),
    )
    return dest


def _never_materialized(src, root):
    raise AssertionError("configured rules dir must not be materialized")


class TestConfiguredRulesDirWins:
    """A rules dir named in the config outranks the copy inside the package."""

    def test_config_rules_dir_beats_package_copy(self, tmp_path):
        rules = _install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")
        assert load_settings(path, str(tmp_path)).rules_dir == rules

    def test_configured_dir_is_scanned_in_place(self, tmp_path, monkeypatch):
        """No copy to a cache: the consumer put the rules where they want them."""
        rules = _install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")

        monkeypatch.setattr(lint_gate, "_materialize_rules_dir", _never_materialized)
        target = tmp_path / "m.py"
        target.write_text("xs = []\nxs.append(1)\n")

        result = LintGate(settings=load_settings(path)).evaluate(
            [str(target)], str(tmp_path)
        )

        assert [v.rule for v in result.violations].count("no-list-append") == 1
        assert os.path.isdir(rules) is True

    def test_deleting_a_configured_rule_disables_it(self, tmp_path):
        """Proves the configured dir -- not the package copy -- is in play."""
        rules = _install_rules(str(tmp_path / ".python-fp-lint"))
        path = _write_config(tmp_path, lint_rules_dir=".python-fp-lint")
        target = tmp_path / "m.py"
        target.write_text("xs = []\nxs.append(1)\n")
        os.unlink(os.path.join(rules, "rules", "no-list-append.yml"))

        result = LintGate(settings=load_settings(path)).evaluate(
            [str(target)], str(tmp_path)
        )

        assert [v.rule for v in result.violations].count("no-list-append") == 0
