# tests/test_max_complexity.py
"""Cyclomatic complexity is a configurable gate, enforced through Ruff's C901.

Fixture calibration (Ruff's AST approximation of the McCabe metric):
`_ONE` scores 1, `_THREE` scores 3, `_FOUR` scores 4. The default ceiling is
3, so `_FOUR` fails out of the box and `_THREE` passes.
"""

import json
import os
import subprocess
import sys

import pytest

from python_fp_lint.lint_gate import (
    _DEFAULT_MAX_COMPLEXITY,
    ConfigError,
    LintGate,
)

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))

_ONE = """
def one(x):
    return x
"""

_THREE = """
def three(x):
    if x == 1:
        return "a"
    if x == 2:
        return "b"
    return "c"
"""

_FOUR = """
def four(x):
    if x == 1:
        return "a"
    if x == 2:
        return "b"
    if x == 3:
        return "c"
    return "d"
"""


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
    # C901 alone keeps these tests about complexity and nothing else.
    path.write_text(json.dumps({"ruff_select": "C901", **values}))
    return str(path)


def _source(tmp_path, name, body):
    target = tmp_path / name
    target.write_text(body)
    return str(target)


def _complexity_rules(result):
    return [v.rule for v in result.violations if v.rule == "C901"]


class TestDefaultThreshold:
    def test_default_is_three(self):
        assert _DEFAULT_MAX_COMPLEXITY == 3

    def test_function_over_the_default_is_flagged(self, tmp_path):
        target = _source(tmp_path, "four.py", _FOUR)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _complexity_rules(result) == ["C901"]

    def test_function_at_the_default_passes(self, tmp_path):
        target = _source(tmp_path, "three.py", _THREE)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _complexity_rules(result) == []


class TestResolution:
    def test_config_value_raises_the_ceiling(self, tmp_path):
        target = _source(tmp_path, "four.py", _FOUR)
        config = _write_config(tmp_path, max_complexity=10)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _complexity_rules(result) == []

    def test_config_value_lowers_the_ceiling(self, tmp_path):
        target = _source(tmp_path, "one.py", _ONE)
        config = _write_config(tmp_path, max_complexity=0)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _complexity_rules(result) == ["C901"]

    def test_constructor_beats_config(self, tmp_path):
        target = _source(tmp_path, "four.py", _FOUR)
        config = _write_config(tmp_path, max_complexity=10)
        gate = LintGate(config_path=config, max_complexity=3)
        result = gate.evaluate([target], str(tmp_path))
        assert _complexity_rules(result) == ["C901"]

    def test_no_config_falls_back_to_the_default(self):
        assert LintGate()._resolve_max_complexity() == _DEFAULT_MAX_COMPLEXITY

    def test_config_value_is_resolved(self, tmp_path):
        config = _write_config(tmp_path, max_complexity=7)
        assert LintGate(config_path=config)._resolve_max_complexity() == 7


class TestInvalidValues:
    def test_non_integer_raises(self, tmp_path):
        config = _write_config(tmp_path, max_complexity="lots")
        with pytest.raises(ConfigError, match="max_complexity"):
            LintGate(config_path=config)._resolve_max_complexity()

    def test_negative_raises(self, tmp_path):
        config = _write_config(tmp_path, max_complexity=-1)
        with pytest.raises(ConfigError, match="max_complexity"):
            LintGate(config_path=config)._resolve_max_complexity()

    def test_bool_is_not_an_integer(self, tmp_path):
        """`true` is an int in Python but nonsense as a complexity ceiling."""
        config = _write_config(tmp_path, max_complexity=True)
        with pytest.raises(ConfigError, match="max_complexity"):
            LintGate(config_path=config)._resolve_max_complexity()


class TestCli:
    def test_flag_overrides_config(self, tmp_path):
        target = _source(tmp_path, "four.py", _FOUR)
        config = _write_config(tmp_path, max_complexity=10)
        result = _run("check", "--config", config, "--max-complexity", "3", target)
        assert result.returncode == 1
        assert "C901" in result.stdout

    def test_flag_relaxes_the_default(self, tmp_path):
        target = _source(tmp_path, "four.py", _FOUR)
        config = _write_config(tmp_path)
        result = _run("check", "--config", config, "--max-complexity", "10", target)
        assert result.returncode == 0

    def test_non_integer_flag_is_rejected(self, tmp_path):
        config = _write_config(tmp_path)
        result = _run("check", "--config", config, "--max-complexity", "lots")
        assert result.returncode == 2


class TestEntryPoints:
    """The ceiling must reach the gates people actually run, not just `check`."""

    def _repo(self, tmp_path):
        def git(*args):
            subprocess.run(
                ["git", *args], cwd=tmp_path, capture_output=True, check=True
            )

        git("init", "-q", "--template=")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "Test")
        return git

    def test_precommit_honours_the_cli_flag(self, tmp_path):
        git = self._repo(tmp_path)
        (tmp_path / "four.py").write_text(_FOUR)
        git("add", "four.py")
        config = _write_config(tmp_path, max_complexity=10)

        relaxed = _run("precommit", "--config", config, cwd=str(tmp_path))
        assert relaxed.returncode == 0

        strict = _run(
            "precommit",
            "--config",
            config,
            "--max-complexity",
            "3",
            cwd=str(tmp_path),
        )
        assert strict.returncode == 1
        assert "C901" in strict.stdout

    def test_hook_check_honours_the_config_file(self, tmp_path):
        from python_fp_lint.hook_check import check_tool_event

        target = _source(tmp_path, "four.py", _FOUR)
        event = {"file_path": target, "content": _FOUR}

        relaxed = _write_config(tmp_path, max_complexity=10)
        assert check_tool_event("Write", event, relaxed) == 0

        strict = _write_config(tmp_path, max_complexity=3)
        assert check_tool_event("Write", event, strict) == 2
