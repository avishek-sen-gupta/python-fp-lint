# tests/test_precommit.py
"""Tests for the staged-diff pre-commit gate."""

import json
import os
import subprocess
import sys

import pytest

from python_fp_lint.precommit import (
    added_line_ranges,
    filter_to_added_lines,
    materialize_staged,
    parse_added_ranges,
    staged_python_files,
)
from python_fp_lint.result import LintViolation

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one committed clean file.

    `--template=` suppresses the user's init.templateDir: these repos must not
    inherit whatever global hooks the developer's machine installs.
    """
    _git(tmp_path, "init", "-q", "--template=")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


CONFIG = os.path.join(REPO_ROOT, "config.example.json")


def _run_precommit(repo, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "python_fp_lint",
            "--format",
            "json",
            "precommit",
            "--config",
            CONFIG,
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


class TestParseAddedRanges:
    def test_single_line_hunk_without_count(self):
        assert parse_added_ranges("@@ -1 +5 @@\n+x = 1\n") == [(5, 5)]

    def test_multi_line_hunk(self):
        assert parse_added_ranges("@@ -1,0 +10,3 @@\n") == [(10, 12)]

    def test_pure_deletion_adds_no_range(self):
        assert parse_added_ranges("@@ -4,2 +3,0 @@\n") == []

    def test_multiple_hunks(self):
        diff = "@@ -1,0 +1,2 @@\n+a\n+b\n@@ -8,0 +20,1 @@\n+c\n"
        assert parse_added_ranges(diff) == [(1, 2), (20, 20)]

    def test_ignores_non_hunk_lines(self):
        diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n"
        assert parse_added_ranges(diff) == [(1, 1)]


class TestFilterToAddedLines:
    def test_keeps_violation_on_added_line(self):
        v = LintViolation(rule="r", file="a.py", line=5, message="m")
        assert filter_to_added_lines([v], {"a.py": [(4, 6)]}) == [v]

    def test_drops_violation_outside_range(self):
        v = LintViolation(rule="r", file="a.py", line=99, message="m")
        assert filter_to_added_lines([v], {"a.py": [(4, 6)]}) == []

    def test_drops_violation_in_unknown_file(self):
        v = LintViolation(rule="r", file="other.py", line=5, message="m")
        assert filter_to_added_lines([v], {"a.py": [(4, 6)]}) == []


class TestStagedDiscovery:
    def test_lists_staged_python_files_only(self, repo):
        (repo / "new.py").write_text("y = 2\n")
        (repo / "notes.txt").write_text("hello\n")
        _git(repo, "add", "new.py", "notes.txt")
        assert staged_python_files(str(repo)) == ["new.py"]

    def test_unstaged_changes_are_not_listed(self, repo):
        (repo / "mod.py").write_text("x = 1\nz = 3\n")
        assert staged_python_files(str(repo)) == []

    def test_added_line_ranges_matches_staged_edit(self, repo):
        (repo / "mod.py").write_text("x = 1\nz = 3\nw = 4\n")
        _git(repo, "add", "mod.py")
        assert added_line_ranges(str(repo), "mod.py") == [(2, 3)]

    def test_materialize_writes_staged_blob_not_worktree(self, repo, tmp_path):
        (repo / "mod.py").write_text("x = 1\nstaged = 2\n")
        _git(repo, "add", "mod.py")
        (repo / "mod.py").write_text("x = 1\nworktree_only = 3\n")
        dest = tmp_path / "out"
        dest.mkdir()
        mapping = materialize_staged(str(repo), ["mod.py"], str(dest))
        [(materialized, rel)] = mapping.items()
        assert rel == "mod.py"
        content = open(materialized).read()
        assert "staged = 2" in content
        assert "worktree_only" not in content


class TestPrecommitCLI:
    def test_clean_staged_change_passes(self, repo):
        (repo / "clean.py").write_text("y = 2\n")
        _git(repo, "add", "clean.py")
        result = _run_precommit(repo)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_violation_on_added_line_fails(self, repo):
        (repo / "bad.py").write_text("d = {}\nd['k'] = 1\n")
        _git(repo, "add", "bad.py")
        result = _run_precommit(repo)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert any(v["rule"] == "no-subscript-mutation" for v in data["violations"])
        assert data["violations"][0]["file"] == "bad.py"

    def test_preexisting_violation_is_not_reported(self, repo):
        legacy = "d = {}\nd['k'] = 1\n"
        (repo / "legacy.py").write_text(legacy)
        _git(repo, "add", "legacy.py")
        _git(repo, "commit", "-qm", "legacy", "--no-verify")
        # Append a clean line — the old violation must not block the commit.
        (repo / "legacy.py").write_text(legacy + "clean = 2\n")
        _git(repo, "add", "legacy.py")
        result = _run_precommit(repo)
        assert result.returncode == 0, result.stdout

    def test_all_lines_reports_preexisting_violation(self, repo):
        legacy = "d = {}\nd['k'] = 1\n"
        (repo / "legacy.py").write_text(legacy)
        _git(repo, "add", "legacy.py")
        _git(repo, "commit", "-qm", "legacy", "--no-verify")
        (repo / "legacy.py").write_text(legacy + "clean = 2\n")
        _git(repo, "add", "legacy.py")
        result = _run_precommit(repo, "--all-lines")
        assert result.returncode == 1

    def test_lints_staged_blob_not_worktree(self, repo):
        (repo / "part.py").write_text("clean = 1\n")
        _git(repo, "add", "part.py")
        # Worktree gains a violation that was never staged — must not block.
        (repo / "part.py").write_text("clean = 1\nd = {}\nd['k'] = 1\n")
        result = _run_precommit(repo)
        assert result.returncode == 0, result.stdout

    def test_nothing_staged_passes(self, repo):
        result = _run_precommit(repo)
        assert result.returncode == 0

    def test_filenames_narrow_the_staged_set(self, repo):
        (repo / "bad.py").write_text("d = {}\nd['k'] = 1\n")
        (repo / "ok.py").write_text("y = 2\n")
        _git(repo, "add", "bad.py", "ok.py")
        assert _run_precommit(repo, "ok.py").returncode == 0
        assert _run_precommit(repo, "bad.py").returncode == 1
