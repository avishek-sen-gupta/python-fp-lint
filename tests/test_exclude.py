# tests/test_exclude.py
"""Exclusion of file globs, from the config file or the --exclude flag."""

import json
import os
import subprocess
import sys

import pytest

from python_fp_lint.hook_check import check_tool_event
from python_fp_lint.lint_gate import LintGate, is_excluded

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _write_config(tmp_path, **values):
    path = tmp_path / "fp.json"
    path.write_text(json.dumps(values))
    return str(path)


def _dirty(tmp_path, relpath):
    """Write a file that violates at least one rule, and return its path."""
    target = tmp_path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("xs = []\nxs.append(1)\n")
    return str(target)


def _run(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "python_fp_lint", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


class TestGlobMatching:
    def test_bare_name_matches_basename_at_any_depth(self):
        assert is_excluded("a/b/foo_pb2.py", "/proj", ["*_pb2.py"])
        assert not is_excluded("a/b/foo.py", "/proj", ["*_pb2.py"])

    def test_star_does_not_cross_a_separator(self):
        assert is_excluded("src/gen.py", "/proj", ["src/*.py"])
        assert not is_excluded("src/deep/gen.py", "/proj", ["src/*.py"])

    def test_double_star_crosses_separators(self):
        assert is_excluded("src/deep/gen.py", "/proj", ["src/**/*.py"])
        assert is_excluded("src/gen.py", "/proj", ["src/**/*.py"])

    def test_trailing_slash_excludes_a_whole_directory(self):
        assert is_excluded("build/a/b.py", "/proj", ["build/"])
        assert not is_excluded("src/build_helper.py", "/proj", ["build/"])

    def test_question_mark_matches_one_character(self):
        assert is_excluded("v1.py", "/proj", ["v?.py"])
        assert not is_excluded("v12.py", "/proj", ["v?.py"])

    def test_absolute_paths_are_matched_relative_to_the_project_root(self):
        assert is_excluded("/proj/tests/a.py", "/proj", ["tests/"])
        assert not is_excluded("/other/tests/a.py", "/proj", ["tests/"])

    def test_no_patterns_excludes_nothing(self):
        assert not is_excluded("anything.py", "/proj", [])

    def test_pattern_is_anchored_at_both_ends(self):
        assert not is_excluded("src/generated_extra.py", "/proj", ["src/generated.py"])


class TestExcludeFromConfig:
    def test_excluded_file_produces_no_violations(self, tmp_path):
        target = _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path, exclude=["generated/"])
        result = LintGate(config_path=path).evaluate([target], str(tmp_path))
        assert result.passed
        assert result.violations == []

    def test_unexcluded_sibling_is_still_linted(self, tmp_path):
        excluded = _dirty(tmp_path, "generated/api.py")
        kept = _dirty(tmp_path, "src/app.py")
        path = _write_config(tmp_path, exclude=["generated/"])
        result = LintGate(config_path=path).evaluate([excluded, kept], str(tmp_path))
        assert not result.passed
        assert {os.path.abspath(v.file) for v in result.violations} == {
            os.path.abspath(kept)
        }

    def test_no_exclude_key_lints_everything(self, tmp_path):
        target = _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path)
        assert not LintGate(config_path=path).evaluate([target], str(tmp_path)).passed

    def test_directory_expansion_respects_exclusions(self, tmp_path):
        _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path, exclude=["generated/"])
        assert (
            LintGate(config_path=path).evaluate([str(tmp_path)], str(tmp_path)).passed
        )

    def test_constructor_argument_beats_config(self, tmp_path):
        target = _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path, exclude=["generated/"])
        gate = LintGate(exclude=[], config_path=path)
        assert not gate.evaluate([target], str(tmp_path)).passed


class TestExcludeOnCLI:
    def test_exclude_flag_skips_matching_files(self, tmp_path):
        target = _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path)
        result = _run(
            "--format",
            "json",
            "check",
            "--config",
            path,
            "--exclude",
            "generated/",
            target,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["violation_count"] == 0

    def test_exclude_flag_overrides_the_config_file(self, tmp_path):
        target = _dirty(tmp_path, "generated/api.py")
        path = _write_config(tmp_path, exclude=["generated/"])
        result = _run(
            "--format",
            "json",
            "check",
            "--config",
            path,
            "--exclude",
            "other/",
            target,
            cwd=str(tmp_path),
        )
        assert result.returncode == 1
        assert json.loads(result.stdout)["violation_count"] > 0


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo, with the user's init template suppressed."""

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )

    git("init", "-q", "--template=")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    return tmp_path


class TestExcludeInPrecommit:
    """Staged files are excluded by their repo-relative path, not the temp copy."""

    @staticmethod
    def _stage(repo, relpath):
        _dirty(repo, relpath)
        subprocess.run(["git", "add", relpath], cwd=repo, check=True)

    def _run_precommit(self, repo, config):
        return _run("--format", "json", "precommit", "--config", config, cwd=str(repo))

    def test_excluded_staged_file_does_not_block_the_commit(self, repo):
        self._stage(repo, "generated/api.py")
        config = _write_config(repo, exclude=["generated/"])
        result = self._run_precommit(repo, config)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["violation_count"] == 0

    def test_unexcluded_staged_file_still_blocks(self, repo):
        self._stage(repo, "src/app.py")
        config = _write_config(repo, exclude=["generated/"])
        result = self._run_precommit(repo, config)
        assert result.returncode == 1
        assert json.loads(result.stdout)["violation_count"] > 0


class TestExcludeInHookCheck:
    """The Claude Code gate judges the real file path, not the temp copy."""

    def test_write_to_an_excluded_path_is_allowed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = _write_config(tmp_path, exclude=["generated/"])
        event = {
            "file_path": str(tmp_path / "generated" / "api.py"),
            "content": "xs = []\nxs.append(1)\n",
        }
        assert check_tool_event("Write", event, config) == 0

    def test_write_elsewhere_is_still_blocked(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = _write_config(tmp_path, exclude=["generated/"])
        event = {
            "file_path": str(tmp_path / "src" / "app.py"),
            "content": "xs = []\nxs.append(1)\n",
        }
        assert check_tool_event("Write", event, config) == 2
