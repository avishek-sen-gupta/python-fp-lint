# tests/test_backends.py
"""Backend discovery and --strict enforcement."""

import os

import pytest

from python_fp_lint import lint_gate
from python_fp_lint.__main__ import _enforce_strict


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
    def test_manifest_declares_both_hook_ids(self):
        import yaml

        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), ".pre-commit-hooks.yaml"
        )
        with open(path) as f:
            hooks = yaml.safe_load(f)
        ids = {h["id"] for h in hooks}
        assert ids == {"python-fp-lint", "python-fp-lint-all"}
        for hook in hooks:
            assert hook["entry"].startswith("python-fp-lint precommit")
            assert hook["types"] == ["python"]
