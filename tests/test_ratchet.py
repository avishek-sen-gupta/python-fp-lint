# tests/test_ratchet.py
"""The violation ratchet: index enumeration, total, verdict, tighten."""

import os
import subprocess

import pytest

from python_fp_lint import baseline, lint_gate, ratchet
from python_fp_lint.lint_gate import LintGate

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG = os.path.join(REPO_ROOT, "config.example.json")

# Two violations: a subscript mutation and a dict.update call.
DIRTY = 'd = {}\nd["k"] = 1\nd.update({"j": 2})\n'
CLEAN = "x = 1\n"


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
    (tmp_path / "mod.py").write_text(CLEAN)
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _gate():
    return LintGate(config_path=CONFIG)


def _total(repo):
    return len(ratchet.total_violations(str(repo), _gate()).violations)


class TestIndexEnumeration:
    def test_lists_tracked_python_files(self, repo):
        (repo / "notes.txt").write_text("hi\n")
        _git(repo, "add", "notes.txt")
        _git(repo, "commit", "-qm", "notes")
        assert ratchet.index_python_files(str(repo)) == ["mod.py"]

    def test_untracked_file_is_not_in_the_index(self, repo):
        (repo / "new.py").write_text(CLEAN)
        assert ratchet.index_python_files(str(repo)) == ["mod.py"]

    def test_staged_addition_is_in_the_index(self, repo):
        (repo / "new.py").write_text(CLEAN)
        _git(repo, "add", "new.py")
        assert sorted(ratchet.index_python_files(str(repo))) == ["mod.py", "new.py"]

    def test_staged_deletion_leaves_the_index(self, repo):
        _git(repo, "rm", "-q", "mod.py")
        assert ratchet.index_python_files(str(repo)) == []

    def test_unstaged_edit_is_reported_dirty(self, repo):
        (repo / "mod.py").write_text(CLEAN + "y = 2\n")
        assert ratchet.unstaged_modified(str(repo)) == {"mod.py"}

    def test_clean_worktree_has_nothing_dirty(self, repo):
        assert ratchet.unstaged_modified(str(repo)) == set()


class TestTotal:
    def test_counts_all_three_backends(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        assert _total(repo) == 2

    def test_untracked_file_does_not_count(self, repo):
        """Review Focus 5's sibling: an untracked file is not in the commit."""
        (repo / "loose.py").write_text(DIRTY)
        assert _total(repo) == 0

    def test_unstaged_edit_is_counted_from_the_index_not_the_worktree(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        (repo / "mod.py").write_text(CLEAN)  # fixed, but not staged
        assert _total(repo) == 2

    def test_unstaged_new_violations_do_not_count(self, repo):
        (repo / "mod.py").write_text(DIRTY)  # dirty in worktree only
        assert _total(repo) == 0

    def test_worktree_deletion_is_counted_from_the_index(self, repo):
        (repo / "mod.py").write_text(DIRTY)
        _git(repo, "add", "mod.py")
        os.unlink(repo / "mod.py")  # deleted, not staged
        assert _total(repo) == 2

    def test_excluded_files_do_not_count(self, tmp_path, repo):
        (repo / "gen.py").write_text(DIRTY)
        _git(repo, "add", "gen.py")
        gate = LintGate(config_path=CONFIG, exclude=["gen.py"])
        assert ratchet.total_violations(str(repo), gate).violations == []

    def test_empty_repo_totals_zero(self, tmp_path):
        """Review Focus 5: no tracked Python files at all."""
        _git(tmp_path, "init", "-q", "--template=")
        _git(tmp_path, "config", "user.email", "t@example.com")
        _git(tmp_path, "config", "user.name", "Test")
        assert _total(tmp_path) == 0


class TestUndecodableFiles:
    def test_latin1_file_does_not_crash_the_run(self, repo):
        """Review Focus 4: legacy repos have non-UTF-8 files."""
        (repo / "legacy.py").write_bytes(b"# caf\xe9\nx = 1\n")
        _git(repo, "add", "legacy.py")
        _total(repo)  # must not raise


class TestChunkedRepo:
    def test_same_total_whether_chunked_or_not(self, repo, monkeypatch):
        """A repo linted in several subprocess batches totals the same."""
        for i in range(5):
            (repo / f"m{i}.py").write_text(DIRTY)
        _git(repo, "add", "-A")
        whole = _total(repo)

        monkeypatch.setattr(lint_gate, "_MAX_PATHS_PER_CALL", 2)
        assert _total(repo) == whole == 10


class TestVerdict:
    def _baseline(self, repo, total):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), total)
        _git(repo, "add", "fp-baseline.json")
        _git(repo, "commit", "-qm", "baseline")
        return str(path)

    def test_rise_does_not_tighten(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=13)
        assert (verdict.recorded, verdict.total, verdict.delta) == (10, 13, 3)
        assert verdict.tightened is False
        assert baseline.read(path) == 10

    def test_equal_does_not_tighten(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=10)
        assert verdict.tightened is False
        assert baseline.read(path) == 10

    def test_fall_rewrites_the_file(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=7)
        assert (verdict.recorded, verdict.total, verdict.delta) == (10, 7, -3)
        assert verdict.tightened is True
        assert baseline.read(path) == 7

    def test_fall_stages_the_file(self, repo):
        path = self._baseline(repo, 10)
        ratchet.apply(str(repo), path, total=7)
        staged = _git(repo, "diff", "--cached", "--name-only")
        assert "fp-baseline.json" in staged

    def test_no_tighten_leaves_the_file_alone(self, repo):
        path = self._baseline(repo, 10)
        verdict = ratchet.apply(str(repo), path, total=7, tighten=False)
        assert verdict.tightened is False
        assert baseline.read(path) == 10
        assert _git(repo, "diff", "--cached", "--name-only") == ""

    def test_missing_baseline_raises(self, repo):
        with pytest.raises(baseline.BaselineError):
            ratchet.apply(str(repo), str(repo / "absent.json"), total=7)


class TestStagingFailure:
    """Review Focus 3: a failed `git add` must not leave a lowered file behind.

    The file on disk would record a total the commit does not contain, and the
    next run would compare against a number nothing in the repo justifies.
    """

    def test_gitignored_baseline_restores_the_previous_total(self, repo):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), 10)
        (repo / ".gitignore").write_text("fp-baseline.json\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-qm", "ignore the baseline")

        with pytest.raises(ratchet.RatchetError, match="git add"):
            ratchet.apply(str(repo), str(path), total=7)
        assert baseline.read(str(path)) == 10

    def test_no_tighten_does_not_touch_git_at_all(self, repo):
        path = repo / "fp-baseline.json"
        baseline.write(str(path), 10)
        (repo / ".gitignore").write_text("fp-baseline.json\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-qm", "ignore the baseline")

        verdict = ratchet.apply(str(repo), str(path), total=7, tighten=False)
        assert verdict.tightened is False
        assert baseline.read(str(path)) == 10
