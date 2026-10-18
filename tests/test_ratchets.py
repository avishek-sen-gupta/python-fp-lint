# tests/test_ratchets.py
"""A Ratchet decides what a commit, `baseline update` and `baseline show` do:
NoRatchet when no baseline is configured, BaselineRatchet when one is. Both
answer every question with a Report."""

import json
import os
import subprocess

import pytest
from gitenv import clean_env

from python_fp_lint import baseline, lint_gate
from python_fp_lint.baseline import BaselineError
from python_fp_lint.lint_gate import BackendError, LintGate
from python_fp_lint.output import OutputFormat, Stream
from python_fp_lint.ratchets import BaselineRatchet, CommitRequest, NoRatchet
from python_fp_lint.reports import CheckReport, RatchetReport
from python_fp_lint.settings import (
    ConfigLayer,
    layer_from_config_file,
    load_settings,
    resolve_ratchet,
)

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG = os.path.join(REPO_ROOT, "config.example.json")
DIRTY = 'd = {}\nd["k"] = 1\n'
NO_BASELINE = (
    'error: no baseline configured; pass --baseline PATH or set "baseline" '
    "in the config file"
)


def _git(repo, *args):
    subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=True, env=clean_env()
    )


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one committed clean file."""
    _git(tmp_path, "init", "-q", "--template=")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "mod.py").write_text("x = 1\n")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


@pytest.fixture
def gate():
    return LintGate(settings=load_settings(CONFIG))


def _stage_dirty(repo):
    (repo / "bad.py").write_text(DIRTY)
    _git(repo, "add", "bad.py")


def _baseline_file(repo, total):
    path = repo / "fp-baseline.json"
    path.write_text(json.dumps({"total": total}))
    return str(path)


class TestResolveRatchet:
    def test_nothing_configured_means_no_ratchet(self):
        assert resolve_ratchet(ConfigLayer(), ConfigLayer()) == NoRatchet()

    def test_falls_back_to_the_config_file_anchored_there(self, tmp_path):
        cfg = tmp_path / "fp.json"
        cfg.write_text(json.dumps({"baseline": "b.json"}))
        ratchet = resolve_ratchet(ConfigLayer(), layer_from_config_file(str(cfg)))
        assert ratchet == BaselineRatchet(str(tmp_path / "b.json"))

    def test_cli_beats_config_file(self):
        ratchet = resolve_ratchet(
            ConfigLayer(baseline="/tmp/cli.json"), ConfigLayer(baseline="/tmp/f.json")
        )
        assert ratchet == BaselineRatchet("/tmp/cli.json")

    def test_cli_baseline_is_not_reanchored(self):
        assert resolve_ratchet(
            ConfigLayer(baseline="rel.json"), ConfigLayer()
        ) == BaselineRatchet("rel.json")


class TestNoRatchet:
    @pytest.mark.parametrize("command", ["record", "show"])
    @pytest.mark.parametrize("fmt", list(OutputFormat))
    def test_baseline_commands_report_no_baseline(self, repo, gate, command, fmt):
        report = getattr(NoRatchet(), command)(str(repo), gate)
        assert (report.render(fmt), report.exit_code, report.stream) == (
            NO_BASELINE,
            2,
            Stream.STDERR,
        )

    def test_blocks_any_staged_violation(self, repo, gate):
        _stage_dirty(repo)
        report = NoRatchet().check_commit(str(repo), gate, CommitRequest())
        assert (type(report), report.exit_code) == (CheckReport, 1)


class TestBaselineRatchet:
    def test_record_writes_the_total(self, repo, gate):
        _stage_dirty(repo)
        path = str(repo / "fp-baseline.json")
        report = BaselineRatchet(path).record(str(repo), gate)
        recorded = json.loads(report.render(OutputFormat.JSON))
        assert (recorded["total"], recorded["path"]) == (baseline.read(path), path)

    def test_show_reads_before_linting(self, repo, gate, monkeypatch):
        """A missing baseline file is the error, even with a backend missing."""
        monkeypatch.setattr(lint_gate, "missing_backends", lambda: ["ruff"])
        with pytest.raises(BaselineError):
            BaselineRatchet(str(repo / "absent.json")).show(str(repo), gate)

    def test_show_compares_recorded_with_current(self, repo, gate):
        path = _baseline_file(repo, 7)
        shown = json.loads(
            BaselineRatchet(path).show(str(repo), gate).render(OutputFormat.JSON)
        )
        assert (shown["baseline"], shown["total"]) == (7, 0)

    def test_check_commit_tightens(self, repo, gate):
        path = _baseline_file(repo, 10)
        report = BaselineRatchet(path).check_commit(str(repo), gate, CommitRequest())
        assert (type(report), report.exit_code, baseline.read(path)) == (
            RatchetReport,
            0,
            0,
        )

    def test_check_commit_honours_no_tighten(self, repo, gate):
        path = _baseline_file(repo, 10)
        BaselineRatchet(path).check_commit(
            str(repo), gate, CommitRequest(tighten=False)
        )
        assert baseline.read(path) == 10

    def test_missing_backend_raises_backend_error(self, repo, gate, monkeypatch):
        monkeypatch.setattr(lint_gate, "missing_backends", lambda: ["ruff"])
        with pytest.raises(
            BackendError, match=r"required lint backend\(s\) not found: ruff"
        ):
            BaselineRatchet(_baseline_file(repo, 1)).check_commit(
                str(repo), gate, CommitRequest()
            )
