# tests/test_max_positional_args.py
"""Positional-parameter count is a configurable gate, enforced through Ruff's PLR0917.

Fixture calibration: Ruff counts positional-only and ordinary parameters, but
not keyword-only ones (after `*`), not `*args`/`**kwargs`, and not the `self`
or `cls` of a method. The default ceiling is 4, so `_FIVE` fails out of the
box and `_FOUR` passes.
"""

import json
import os
import subprocess
import sys

import pytest
from gitenv import clean_env

from python_fp_lint.lint_gate import (
    _DEFAULT_MAX_POSITIONAL_ARGS,
    ConfigError,
    LintGate,
    LintSettings,
)
from python_fp_lint.settings import (
    ConfigLayer,
    layer_from_config_file,
    load_settings,
    resolve_settings,
)

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _function(name: str, positional: int, keyword_only: int = 0) -> str:
    """A function with exactly `positional` positional parameters."""
    params = [f"p{i}" for i in range(positional)]
    kwonly = [f"k{i}" for i in range(keyword_only)]
    signature = ", ".join(params + (["*", *kwonly] if kwonly else []))
    return f"def {name}({signature}):\n    return None\n"


_ONE = _function("one", 1)
_FOUR = _function("four", 4)
_FIVE = _function("five", 5)
_FOUR_PLUS_KEYWORD_ONLY = _function("wide", 4, keyword_only=6)
_METHOD_WITH_FOUR = (
    "class Holder:\n    def method(self, a, b, c, d):\n        return None\n"
)
_POSITIONAL_ONLY_FIVE = "def slashed(a, b, /, c, d, e):\n    return None\n"


def _run(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "python_fp_lint", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=clean_env(PYTHONPATH=REPO_ROOT),
    )


def _write_config(tmp_path, **values):
    path = tmp_path / "fp.json"
    # PLR0917 alone keeps these tests about positional parameters and nothing else.
    path.write_text(json.dumps({"ruff_select": "PLR0917", **values}))
    return str(path)


def _source(tmp_path, name, body):
    target = tmp_path / name
    target.write_text(body)
    return str(target)


def _positional_rules(result):
    return [v.rule for v in result.violations if v.rule == "PLR0917"]


def _evaluate(tmp_path, body, **config):
    target = _source(tmp_path, "target.py", body)
    gate = LintGate(settings=load_settings(_write_config(tmp_path, **config)))
    return gate.evaluate([target], str(tmp_path))


class TestDefaultThreshold:
    def test_default_is_four(self):
        assert _DEFAULT_MAX_POSITIONAL_ARGS == 4

    def test_default_select_includes_the_rule(self, tmp_path):
        target = _source(tmp_path, "five.py", _FIVE)
        result = LintGate().evaluate([target], str(tmp_path))
        assert _positional_rules(result) == ["PLR0917"]

    def test_function_over_the_default_is_flagged(self, tmp_path):
        assert _positional_rules(_evaluate(tmp_path, _FIVE)) == ["PLR0917"]

    def test_function_at_the_default_passes(self, tmp_path):
        assert _positional_rules(_evaluate(tmp_path, _FOUR)) == []


class TestCountsOnlyPositionalParameters:
    def test_keyword_only_parameters_are_not_counted(self, tmp_path):
        result = _evaluate(tmp_path, _FOUR_PLUS_KEYWORD_ONLY)
        assert _positional_rules(result) == []

    def test_self_is_not_counted(self, tmp_path):
        assert _positional_rules(_evaluate(tmp_path, _METHOD_WITH_FOUR)) == []

    def test_positional_only_parameters_are_counted(self, tmp_path):
        result = _evaluate(tmp_path, _POSITIONAL_ONLY_FIVE)
        assert _positional_rules(result) == ["PLR0917"]


class TestResolution:
    def test_config_value_raises_the_ceiling(self, tmp_path):
        result = _evaluate(tmp_path, _FIVE, max_positional_args=10)
        assert _positional_rules(result) == []

    def test_config_value_lowers_the_ceiling(self, tmp_path):
        result = _evaluate(tmp_path, _ONE, max_positional_args=0)
        assert _positional_rules(result) == ["PLR0917"]

    def test_constructor_beats_config(self, tmp_path):
        target = _source(tmp_path, "five.py", _FIVE)
        config = _write_config(tmp_path, max_positional_args=10)
        gate = LintGate(
            settings=resolve_settings(
                ConfigLayer(max_positional_args=4), layer_from_config_file(config), "."
            )
        )
        result = gate.evaluate([target], str(tmp_path))
        assert _positional_rules(result) == ["PLR0917"]

    def test_no_config_falls_back_to_the_default(self):
        assert LintSettings().max_positional_args == _DEFAULT_MAX_POSITIONAL_ARGS

    def test_config_value_is_resolved(self, tmp_path):
        config = _write_config(tmp_path, max_positional_args=7)
        assert load_settings(config).max_positional_args == 7


class TestInvalidValues:
    def test_non_integer_raises(self, tmp_path):
        config = _write_config(tmp_path, max_positional_args="lots")
        with pytest.raises(ConfigError, match="max_positional_args"):
            load_settings(config)

    def test_negative_raises(self, tmp_path):
        config = _write_config(tmp_path, max_positional_args=-1)
        with pytest.raises(ConfigError, match="max_positional_args"):
            load_settings(config)

    def test_bool_is_not_an_integer(self, tmp_path):
        """`true` is an int in Python but nonsense as a parameter ceiling."""
        config = _write_config(tmp_path, max_positional_args=True)
        with pytest.raises(ConfigError, match="max_positional_args"):
            load_settings(config)


class TestCli:
    def test_flag_overrides_config(self, tmp_path):
        target = _source(tmp_path, "five.py", _FIVE)
        config = _write_config(tmp_path, max_positional_args=10)
        result = _run("check", "--config", config, "--max-positional-args", "4", target)
        assert result.returncode == 1
        assert result.stdout.count("PLR0917") == 1

    def test_flag_relaxes_the_default(self, tmp_path):
        target = _source(tmp_path, "five.py", _FIVE)
        config = _write_config(tmp_path)
        result = _run(
            "check", "--config", config, "--max-positional-args", "10", target
        )
        assert result.returncode == 0

    def test_non_integer_flag_is_rejected(self, tmp_path):
        config = _write_config(tmp_path)
        result = _run("check", "--config", config, "--max-positional-args", "lots")
        assert result.returncode == 2


class TestEntryPoints:
    """The ceiling must reach the gates people actually run, not just `check`."""

    def _repo(self, tmp_path):
        def git(*args):
            subprocess.run(
                ["git", *args],
                cwd=tmp_path,
                capture_output=True,
                check=True,
                env=clean_env(),
            )

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        return git

    def test_precommit_honours_the_cli_flag(self, tmp_path):
        git = self._repo(tmp_path)
        (tmp_path / "five.py").write_text(_FIVE)
        git("add", "five.py")
        config = _write_config(tmp_path, max_positional_args=10)

        relaxed = _run("precommit", "--config", config, cwd=str(tmp_path))
        assert relaxed.returncode == 0

        strict = _run(
            "precommit",
            "--config",
            config,
            "--max-positional-args",
            "4",
            cwd=str(tmp_path),
        )
        assert strict.returncode == 1
        assert strict.stdout.count("PLR0917") == 1

    def test_hook_check_honours_the_config_file(self, tmp_path):
        from python_fp_lint.hook_check import check_tool_event

        target = _source(tmp_path, "five.py", _FIVE)
        event = {"file_path": target, "content": _FIVE}

        relaxed = _write_config(tmp_path, max_positional_args=10)
        assert check_tool_event("Write", event, load_settings(relaxed)) == 0

        strict = _write_config(tmp_path, max_positional_args=4)
        assert check_tool_event("Write", event, load_settings(strict)) == 2
