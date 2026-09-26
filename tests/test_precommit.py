# tests/test_precommit.py
"""Tests for the staged-content pre-commit gate."""

import json
import os
import subprocess
import sys

import pytest

from python_fp_lint.precommit import materialize_staged, staged_python_files

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG = os.path.join(REPO_ROOT, "config.example.json")


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


class TestStagedDiscovery:
    def test_lists_staged_python_files_only(self, repo):
        (repo / "new.py").write_text("y = 2\n")
        (repo / "notes.txt").write_text("hello\n")
        _git(repo, "add", "new.py", "notes.txt")
        assert staged_python_files(str(repo)) == ["new.py"]

    def test_unstaged_changes_are_not_listed(self, repo):
        (repo / "mod.py").write_text("x = 1\nz = 3\n")
        assert staged_python_files(str(repo)) == []

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

    def test_materialize_copies_a_non_utf8_blob_verbatim(self, repo, tmp_path):
        """C2: `git show` used to decode its stdout and die on latin-1."""
        latin1 = b'# caf\xe9\nd = {}\nd["k"] = 1\n'
        (repo / "legacy.py").write_bytes(latin1)
        _git(repo, "add", "legacy.py")
        dest = tmp_path / "out"
        dest.mkdir()
        mapping = materialize_staged(str(repo), ["legacy.py"], str(dest))
        [(materialized, _)] = mapping.items()
        assert open(materialized, "rb").read() == latin1

    def test_non_utf8_staged_file_is_linted_not_crashed(self, repo):
        """It reports Ruff's E902, rather than dying in the materializer."""
        (repo / "legacy.py").write_bytes(b'# caf\xe9\nd = {}\nd["k"] = 1\n')
        _git(repo, "add", "legacy.py")
        result = _run_precommit(repo)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Traceback" not in result.stderr
        data = json.loads(result.stdout)
        assert [(v["rule"], v["file"]) for v in data["violations"]] == [
            ("E902", "legacy.py")
        ]


class TestPrecommitCLI:
    def test_clean_staged_change_passes(self, repo):
        (repo / "clean.py").write_text("y = 2\n")
        _git(repo, "add", "clean.py")
        result = _run_precommit(repo)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_violation_in_staged_file_fails(self, repo):
        (repo / "bad.py").write_text("d = {}\nd['k'] = 1\n")
        _git(repo, "add", "bad.py")
        result = _run_precommit(repo)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert any(v["rule"] == "no-subscript-mutation" for v in data["violations"])
        assert data["violations"][0]["file"] == "bad.py"

    def test_preexisting_violation_also_blocks(self, repo):
        """Every violation in a staged file counts, not just newly added ones."""
        legacy = "d = {}\nd['k'] = 1\n"
        (repo / "legacy.py").write_text(legacy)
        _git(repo, "add", "legacy.py")
        _git(repo, "commit", "-qm", "legacy", "--no-verify")
        # Append a clean line — the pre-existing violation still blocks.
        (repo / "legacy.py").write_text(legacy + "clean = 2\n")
        _git(repo, "add", "legacy.py")
        result = _run_precommit(repo)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert any(v["rule"] == "no-subscript-mutation" for v in data["violations"])

    def test_untouched_file_does_not_block(self, repo):
        """A dirty file that isn't staged is irrelevant to this commit."""
        (repo / "legacy.py").write_text("d = {}\nd['k'] = 1\n")
        _git(repo, "add", "legacy.py")
        _git(repo, "commit", "-qm", "legacy", "--no-verify")
        (repo / "clean.py").write_text("y = 2\n")
        _git(repo, "add", "clean.py")
        assert _run_precommit(repo).returncode == 0

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
