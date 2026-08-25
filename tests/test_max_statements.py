# tests/test_max_statements.py
"""Statement count is a configurable gate, enforced through Ruff's PLR0915.

Fixture calibration: Ruff counts *statements*, not physical lines, and (like
pylint) does not count a function's trailing `return`. `_TEN` therefore scores
10 and `_ELEVEN` scores 11, whatever their line counts. The default ceiling is
10, so `_ELEVEN` fails out of the box and `_TEN` passes.
"""

import json
import os
import subprocess
import sys

import pytest

from python_fp_lint.lint_gate import (
    _DEFAULT_MAX_STATEMENTS,
    ConfigError,
    LintGate,
)

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _function(name: str, statements: int) -> str:
    """A function whose Ruff statement count is exactly `statements`."""
    body = [f"    a{i} = x + {i}" for i in range(1, statements + 1)]
    return "\n".join([f"def {name}(x):", *body, f"    return a{statements}", ""])


_ONE = _function("one", 1)
_TEN = _function("ten", 10)
_ELEVEN = _function("eleven", 11)

# The same 10 statements folded onto one physical line each way round: the gate
# must count statements, so neither the long form nor the short form matters.
_ELEVEN_ON_FEW_LINES = (
    "def dense(x):\n"
    + "".join(f"    a{i} = x + {i};" for i in range(1, 12))
    + f"\n    return a11\n"
)


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
    # PLR0915 alone keeps these tests about statement count and nothing else.
    path.write_text(json.dumps({"ruff_select": "PLR0915", **values}))
    return str(path)


def _source(tmp_path, name, body):
    target = tmp_path / name
    target.write_text(body)
    return str(target)


def _statement_rules(result):
    return [v.rule for v in result.violations if v.rule == "PLR0915"]


class TestDefaultThreshold:
    def test_default_is_ten(self):
        assert _DEFAULT_MAX_STATEMENTS == 10

    def test_function_over_the_default_is_flagged(self, tmp_path):
        target = _source(tmp_path, "eleven.py", _ELEVEN)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == ["PLR0915"]

    def test_function_at_the_default_passes(self, tmp_path):
        target = _source(tmp_path, "ten.py", _TEN)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == []


class TestCountsStatementsNotLines:
    def test_statements_crammed_onto_few_lines_still_fail(self, tmp_path):
        """Semicolon-joined statements are still statements."""
        target = _source(tmp_path, "dense.py", _ELEVEN_ON_FEW_LINES)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == ["PLR0915"]

    def test_a_long_but_thin_function_passes(self, tmp_path):
        """Blank lines, comments and wrapped expressions are not statements."""
        padding = "\n".join("    # filler" for _ in range(40))
        body = f"def thin(x):\n{padding}\n    y = (\n        x\n        + 1\n    )\n    return y\n"
        target = _source(tmp_path, "thin.py", body)
        config = _write_config(tmp_path)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == []


class TestResolution:
    def test_config_value_raises_the_ceiling(self, tmp_path):
        target = _source(tmp_path, "eleven.py", _ELEVEN)
        config = _write_config(tmp_path, max_statements=50)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == []

    def test_config_value_lowers_the_ceiling(self, tmp_path):
        target = _source(tmp_path, "one.py", _ONE)
        config = _write_config(tmp_path, max_statements=0)
        result = LintGate(config_path=config).evaluate([target], str(tmp_path))
        assert _statement_rules(result) == ["PLR0915"]

    def test_constructor_beats_config(self, tmp_path):
        target = _source(tmp_path, "eleven.py", _ELEVEN)
        config = _write_config(tmp_path, max_statements=50)
        gate = LintGate(config_path=config, max_statements=10)
        result = gate.evaluate([target], str(tmp_path))
        assert _statement_rules(result) == ["PLR0915"]

    def test_no_config_falls_back_to_the_default(self):
        assert LintGate()._resolve_max_statements() == _DEFAULT_MAX_STATEMENTS

    def test_config_value_is_resolved(self, tmp_path):
        config = _write_config(tmp_path, max_statements=25)
        assert LintGate(config_path=config)._resolve_max_statements() == 25


class TestInvalidValues:
    def test_non_integer_raises(self, tmp_path):
        config = _write_config(tmp_path, max_statements="lots")
        with pytest.raises(ConfigError, match="max_statements"):
            LintGate(config_path=config)._resolve_max_statements()

    def test_negative_raises(self, tmp_path):
        config = _write_config(tmp_path, max_statements=-1)
        with pytest.raises(ConfigError, match="max_statements"):
            LintGate(config_path=config)._resolve_max_statements()

    def test_bool_is_not_an_integer(self, tmp_path):
        """`true` is an int in Python but nonsense as a statement ceiling."""
        config = _write_config(tmp_path, max_statements=True)
        with pytest.raises(ConfigError, match="max_statements"):
            LintGate(config_path=config)._resolve_max_statements()


class TestCli:
    def test_flag_overrides_config(self, tmp_path):
        target = _source(tmp_path, "eleven.py", _ELEVEN)
        config = _write_config(tmp_path, max_statements=50)
        result = _run("check", "--config", config, "--max-statements", "10", target)
        assert result.returncode == 1
        assert "PLR0915" in result.stdout

    def test_flag_relaxes_the_default(self, tmp_path):
        target = _source(tmp_path, "eleven.py", _ELEVEN)
        config = _write_config(tmp_path)
        result = _run("check", "--config", config, "--max-statements", "50", target)
        assert result.returncode == 0

    def test_non_integer_flag_is_rejected(self, tmp_path):
        config = _write_config(tmp_path)
        result = _run("check", "--config", config, "--max-statements", "lots")
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
        (tmp_path / "eleven.py").write_text(_ELEVEN)
        git("add", "eleven.py")
        config = _write_config(tmp_path, max_statements=50)

        relaxed = _run("precommit", "--config", config, cwd=str(tmp_path))
        assert relaxed.returncode == 0

        strict = _run(
            "precommit",
            "--config",
            config,
            "--max-statements",
            "10",
            cwd=str(tmp_path),
        )
        assert strict.returncode == 1
        assert "PLR0915" in strict.stdout

    def test_hook_check_honours_the_config_file(self, tmp_path):
        from python_fp_lint.hook_check import check_tool_event

        target = _source(tmp_path, "eleven.py", _ELEVEN)
        event = {"file_path": target, "content": _ELEVEN}

        relaxed = _write_config(tmp_path, max_statements=50)
        assert check_tool_event("Write", event, relaxed) == 0

        strict = _write_config(tmp_path, max_statements=10)
        assert check_tool_event("Write", event, strict) == 2
