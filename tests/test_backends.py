# tests/test_backends.py
"""Backend discovery and --strict enforcement."""

import json
import os
import subprocess
from dataclasses import dataclass, field

import pytest

from python_fp_lint import lint_gate
from python_fp_lint.__main__ import _enforce_strict


@dataclass
class _Completed:
    """Stand-in for subprocess.CompletedProcess."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    args: list = field(default_factory=list)


class _Args:
    def __init__(self, strict):
        self.strict = strict


class TestWhich:
    def test_prefers_path(self, monkeypatch):
        monkeypatch.setattr(lint_gate.shutil, "which", lambda n: f"/usr/bin/{n}")
        assert lint_gate._which("ruff") == "/usr/bin/ruff"

    def test_falls_back_to_interpreter_bin_dir(self, monkeypatch, tmp_path):
        sibling = tmp_path / "bin" / "ruff"
        sibling.parent.mkdir()
        sibling.write_text("#!/bin/sh\n")
        sibling.chmod(0o755)
        monkeypatch.setattr(lint_gate.shutil, "which", lambda _n: None)
        monkeypatch.setattr(lint_gate.sys, "executable", str(tmp_path / "bin/python"))
        assert lint_gate._which("ruff") == str(sibling)

    def test_returns_none_when_nowhere(self, monkeypatch, tmp_path):
        monkeypatch.setattr(lint_gate.shutil, "which", lambda _n: None)
        monkeypatch.setattr(lint_gate.sys, "executable", str(tmp_path / "python"))
        assert lint_gate._which("ruff") is None

    def test_ignores_non_executable_sibling(self, monkeypatch, tmp_path):
        sibling = tmp_path / "ruff"
        sibling.write_text("not executable\n")
        sibling.chmod(0o644)
        monkeypatch.setattr(lint_gate.shutil, "which", lambda _n: None)
        monkeypatch.setattr(lint_gate.sys, "executable", str(tmp_path / "python"))
        assert lint_gate._which("ruff") is None


class TestMissingBackends:
    def test_none_missing_when_both_found(self, monkeypatch):
        monkeypatch.setattr(lint_gate, "_which", lambda n: f"/usr/bin/{n}")
        assert lint_gate.missing_backends() == []

    def test_reports_both_when_absent(self, monkeypatch):
        monkeypatch.setattr(lint_gate, "_which", lambda _n: None)
        assert lint_gate.missing_backends() == ["ast-grep", "ruff"]

    def test_reports_only_the_absent_one(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate, "_which", lambda n: "/usr/bin/ruff" if n == "ruff" else None
        )
        assert lint_gate.missing_backends() == ["ast-grep"]

    def test_real_environment_has_both_backends(self):
        """The declared wheel dependencies must actually be reachable."""
        assert lint_gate.missing_backends() == []


class TestEnforceStrict:
    def test_exits_two_when_backend_missing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "python_fp_lint.__main__.missing_backends", lambda: ["ast-grep"]
        )
        with pytest.raises(SystemExit) as exc:
            _enforce_strict(_Args(strict=True))
        assert exc.value.code == 2
        assert "ast-grep" in capsys.readouterr().err

    def test_silent_when_nothing_missing(self, monkeypatch):
        monkeypatch.setattr("python_fp_lint.__main__.missing_backends", lambda: [])
        _enforce_strict(_Args(strict=True))  # must not raise

    def test_no_check_without_strict_flag(self, monkeypatch):
        monkeypatch.setattr(
            "python_fp_lint.__main__.missing_backends", lambda: ["ruff"]
        )
        _enforce_strict(_Args(strict=False))  # must not raise


class TestPreCommitHooksManifest:
    def test_manifest_declares_the_hook(self):
        import yaml

        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".pre-commit-hooks.yaml"
        )
        with open(path) as f:
            hooks = yaml.safe_load(f)
        by_id = {h["id"]: h for h in hooks}
        assert set(by_id) == {"python-fp-lint", "python-fp-lint-check"}
        for hook in hooks:
            assert hook["types"] == ["python"]
        assert by_id["python-fp-lint"]["entry"].startswith("python-fp-lint precommit")

    def test_commit_gate_runs_only_at_the_pre_commit_stage(self):
        """Unset `stages` means every installed stage: with a commit-msg hook
        also installed, the gate would run a second time per commit."""
        import yaml

        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".pre-commit-hooks.yaml"
        )
        with open(path) as f:
            hook = next(h for h in yaml.safe_load(f) if h["id"] == "python-fp-lint")
        assert hook["stages"] == ["pre-commit"]

    def test_check_hook_lints_the_worktree_on_demand_only(self):
        import yaml

        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".pre-commit-hooks.yaml"
        )
        with open(path) as f:
            hook = next(
                h for h in yaml.safe_load(f) if h["id"] == "python-fp-lint-check"
            )
        assert hook["entry"].startswith("python-fp-lint check")
        assert hook["stages"] == ["manual"]


class TestBackendFailuresRaise:
    """A backend that did not run must not report zero violations.

    Under the ratchet, zero reads as an improvement and tightens the baseline
    to 0, destroying the debt record.
    """

    def test_ruff_timeout_raises(self, monkeypatch):
        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="ruff", timeout=30)

        monkeypatch.setattr(lint_gate.subprocess, "run", timeout)
        with pytest.raises(lint_gate.BackendError, match="timed out"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_oserror_raises(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise OSError(7, "Argument list too long")

        monkeypatch.setattr(lint_gate.subprocess, "run", boom)
        with pytest.raises(lint_gate.BackendError, match="ruff"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_unparseable_output_raises(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess,
            "run",
            lambda *_a, **_k: _Completed(stdout="not json at all"),
        )
        with pytest.raises(lint_gate.BackendError, match="unparseable"):
            lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3)

    def test_ruff_empty_output_is_still_zero_violations(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess, "run", lambda *_a, **_k: _Completed(stdout="")
        )
        assert lint_gate._run_ruff("/usr/bin/ruff", ["a.py"], "F", 3) == []

    def test_sg_timeout_raises(self, monkeypatch):
        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="sg", timeout=30)

        monkeypatch.setattr(lint_gate.subprocess, "run", timeout)
        with pytest.raises(lint_gate.BackendError, match="timed out"):
            lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])

    def test_sg_ndjson_fallback_still_works(self, monkeypatch):
        line = json.dumps(
            {
                "ruleId": "no-list-append",
                "file": "a.py",
                "range": {"start": {"line": 4}},
                "message": "m",
            }
        )
        monkeypatch.setattr(
            lint_gate.subprocess, "run", lambda *_a, **_k: _Completed(stdout=line)
        )
        [violation] = lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])
        assert violation.rule == "no-list-append"
        assert violation.line == 5

    def test_sg_garbage_output_raises(self, monkeypatch):
        monkeypatch.setattr(
            lint_gate.subprocess,
            "run",
            lambda *_a, **_k: _Completed(stdout="{ not json\nalso not json"),
        )
        with pytest.raises(lint_gate.BackendError, match="unparseable"):
            lint_gate._run_sg("/usr/bin/sg", "/rules", ["a.py"])


class TestArgvChunking:
    def test_chunks_at_the_limit(self):
        chunks = lint_gate._chunked([str(i) for i in range(2500)], size=1000)
        assert [len(c) for c in chunks] == [1000, 1000, 500]

    def test_empty_input_yields_no_chunks(self):
        assert lint_gate._chunked([]) == []

    def test_ruff_runs_once_per_chunk_and_concatenates(self, monkeypatch):
        calls = []

        def record(cmd, **_kwargs):
            paths = [a for a in cmd if a.endswith(".py")]
            calls.append(len(paths))
            entry = {
                "code": "F401",
                "filename": paths[0],
                "location": {"row": 1},
                "message": "m",
            }
            return _Completed(stdout=json.dumps([entry]))

        monkeypatch.setattr(lint_gate.subprocess, "run", record)
        files = [f"f{i}.py" for i in range(2500)]
        violations = lint_gate._run_ruff("/usr/bin/ruff", files, "F", 3)
        assert calls == [1000, 1000, 500]
        assert len(violations) == 3

    def test_sg_runs_once_per_chunk_and_concatenates(self, monkeypatch):
        calls = []

        def record(cmd, **_kwargs):
            paths = [a for a in cmd if a.endswith(".py")]
            calls.append(len(paths))
            entry = {
                "ruleId": "no-list-append",
                "file": paths[0],
                "range": {"start": {"line": 0}},
                "message": "m",
            }
            return _Completed(stdout=json.dumps([entry]))

        monkeypatch.setattr(lint_gate.subprocess, "run", record)
        files = [f"f{i}.py" for i in range(2500)]
        violations = lint_gate._run_sg("/usr/bin/sg", "/rules", files)
        assert calls == [1000, 1000, 500]
        assert len(violations) == 3
