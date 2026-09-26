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


class TestMaterializedIndex:
    """What `git checkout-index -a` puts in the temp tree is what gets linted.

    These replace the old clean/dirty enumeration tests: the total is now a
    function of the index by construction rather than by a per-file choice
    between the worktree copy and `git show :path`.
    """

    def _materialize(self, repo, tmp_path):
        dest = tmp_path / "idx"
        ratchet.materialize_index(str(repo), str(dest))
        return dest

    def test_writes_tracked_python_files(self, repo, tmp_path):
        dest = self._materialize(repo, tmp_path)
        assert ratchet._python_files_under(str(dest)) == ["mod.py"]

    def test_writes_non_python_files_too(self, repo, tmp_path):
        """C1: Ruff's directory-scoped settings need their config file here."""
        (repo / "pyproject.toml").write_text("[tool.ruff]\n")
        _git(repo, "add", "pyproject.toml")
        dest = self._materialize(repo, tmp_path)
        assert (dest / "pyproject.toml").read_text() == "[tool.ruff]\n"

    def test_untracked_file_is_not_materialized(self, repo, tmp_path):
        (repo / "new.py").write_text(CLEAN)
        dest = self._materialize(repo, tmp_path)
        assert ratchet._python_files_under(str(dest)) == ["mod.py"]

    def test_staged_addition_is_materialized(self, repo, tmp_path):
        (repo / "new.py").write_text(CLEAN)
        _git(repo, "add", "new.py")
        dest = self._materialize(repo, tmp_path)
        assert ratchet._python_files_under(str(dest)) == ["mod.py", "new.py"]

    def test_staged_deletion_is_not_materialized(self, repo, tmp_path):
        _git(repo, "rm", "-q", "mod.py")
        dest = self._materialize(repo, tmp_path)
        assert ratchet._python_files_under(str(dest)) == []

    def test_index_content_wins_over_an_unstaged_edit(self, repo, tmp_path):
        (repo / "mod.py").write_text(CLEAN + "y = 2\n")
        dest = self._materialize(repo, tmp_path)
        assert (dest / "mod.py").read_text() == CLEAN

    def test_nested_paths_keep_their_shape(self, repo, tmp_path):
        (repo / "pkg").mkdir()
        (repo / "pkg" / "deep.py").write_text(CLEAN)
        _git(repo, "add", "pkg/deep.py")
        dest = self._materialize(repo, tmp_path)
        assert ratchet._python_files_under(str(dest)) == [
            "mod.py",
            os.path.join("pkg", "deep.py"),
        ]


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


class TestRuffDirectoryConfig:
    """C1: the total must be a function of the committed content alone.

    Ruff resolves `per-file-ignores` and friends from the closest
    `pyproject.toml` above each file. Materializing only `.py` files left
    those settings behind, so a file's contribution depended on whether its
    worktree copy happened to match the index.
    """

    LEGACY = "import os\nimport sys\n\n\ndef f(x):\n    return x == None\n"

    def _repo_with_per_file_ignores(self, repo):
        (repo / "pyproject.toml").write_text(
            '[tool.ruff.lint.per-file-ignores]\n"legacy/**" = ["F401", "E711"]\n'
        )
        (repo / "legacy").mkdir()
        (repo / "legacy" / "mod.py").write_text(self.LEGACY)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "legacy")
        return repo

    def test_per_file_ignores_apply_to_a_clean_worktree(self, repo):
        repo = self._repo_with_per_file_ignores(repo)
        assert _total(repo) == 0

    def test_per_file_ignores_apply_to_a_dirty_worktree(self, repo):
        """The reviewer's reproduction: the index is unchanged, so is the total."""
        repo = self._repo_with_per_file_ignores(repo)
        clean = _total(repo)
        (repo / "legacy" / "mod.py").write_text(self.LEGACY + "\n")  # dirty, unstaged
        assert _total(repo) == clean == 0

    def test_the_same_file_outside_the_ignored_directory_still_counts(self, repo):
        repo = self._repo_with_per_file_ignores(repo)
        (repo / "current.py").write_text(self.LEGACY)
        _git(repo, "add", "current.py")
        assert _total(repo) > 0


class TestUndecodableFiles:
    """Review Focus 4: legacy repos have non-UTF-8 files.

    Such a file contributes exactly one violation -- Ruff's E902, "stream did
    not contain valid UTF-8" -- and must never abort the run.
    """

    LATIN1 = b'# caf\xe9\nd = {}\nd["k"] = 1\n'

    def _reported(self, repo):
        violations = ratchet.total_violations(str(repo), _gate()).violations
        return [(v.rule, v.file) for v in violations]

    def test_latin1_file_staged_clean(self, repo):
        (repo / "legacy.py").write_bytes(self.LATIN1)
        _git(repo, "add", "legacy.py")
        assert self._reported(repo) == [("E902", "legacy.py")]

    def test_latin1_file_with_an_unstaged_edit(self, repo):
        """C2: the materialization path, which `git show`'s decode used to kill.

        The worktree copy is clean ASCII and would contribute nothing, so the
        one E902 also proves the index content is what was counted.
        """
        (repo / "legacy.py").write_bytes(self.LATIN1)
        _git(repo, "add", "legacy.py")
        (repo / "legacy.py").write_bytes(b"x = 1\n")  # re-encoded, but not staged
        assert self._reported(repo) == [("E902", "legacy.py")]

    def test_latin1_bytes_survive_materialization(self, repo, tmp_path):
        (repo / "legacy.py").write_bytes(self.LATIN1)
        _git(repo, "add", "legacy.py")
        dest = tmp_path / "idx"
        ratchet.materialize_index(str(repo), str(dest))
        assert (dest / "legacy.py").read_bytes() == self.LATIN1


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
