# tests/test_precommit_installer.py
"""Round-trip tests for install-precommit.sh / uninstall-precommit.sh."""

import json
import os
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
INSTALL = os.path.join(REPO_ROOT, "install-precommit.sh")
UNINSTALL = os.path.join(REPO_ROOT, "uninstall-precommit.sh")
REPO_URL = "https://github.com/avishek-sen-gupta/python-fp-lint"


@pytest.fixture
def bin_dir(tmp_path_factory):
    """A PATH entry holding only python3, ahead of /usr/bin:/bin.

    Keeps the developer's `pre-commit` off PATH, so the installer skips
    `pre-commit install` instead of rewriting the test repo's git hooks.
    """
    d = tmp_path_factory.mktemp("bin")
    os.symlink(sys.executable, d / "python3")
    return d


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "--template=", str(tmp_path)], check=True)
    return tmp_path


def _sh(script, repo, bin_dir):
    return subprocess.run(
        ["/bin/sh", script],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
    )


def _install(repo, bin_dir):
    result = _sh(INSTALL, repo, bin_dir)
    assert result.returncode == 0, result.stderr
    return result


def _uninstall(repo, bin_dir):
    result = _sh(UNINSTALL, repo, bin_dir)
    assert result.returncode == 0, result.stderr
    return result


class TestFreshRepo:
    def test_removes_everything_the_installer_created(self, repo, bin_dir):
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert not (repo / ".pre-commit-config.yaml").exists()
        assert not (repo / ".python-fp-lint").exists()
        assert not (repo / "fp.json").exists()

    def test_is_a_no_op_when_nothing_is_installed(self, repo, bin_dir):
        _uninstall(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [".git"]

    def test_running_twice_is_harmless(self, repo, bin_dir):
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [".git"]

    def test_refuses_outside_a_git_repo_root(self, tmp_path, bin_dir):
        result = _sh(UNINSTALL, tmp_path, bin_dir)
        assert result.returncode == 1
        assert "not a git repository root" in result.stderr


def _hooks(repo):
    config = yaml.safe_load((repo / ".pre-commit-config.yaml").read_text())
    (ours,) = [r for r in config["repos"] if r["repo"] == REPO_URL]
    return {h["id"]: h for h in ours["hooks"]}


class TestInstallWiresBothHooks:
    def test_wires_the_commit_gate_and_the_on_demand_check(self, repo, bin_dir):
        _install(repo, bin_dir)
        hooks = _hooks(repo)
        assert set(hooks) == {"python-fp-lint", "python-fp-lint-check"}
        for hook in hooks.values():
            assert hook["args"] == ["--config", "fp.json"]

    def test_adds_the_check_hook_to_an_older_install(self, repo, bin_dir):
        (repo / ".pre-commit-config.yaml").write_text(
            "repos:\n"
            f"  - repo: {REPO_URL}\n"
            "    rev: main\n"
            "    hooks:\n"
            "      - id: python-fp-lint\n"
            "        args: [--config, fp.json]\n"
            "  - repo: https://github.com/psf/black\n"
            "    rev: 24.1.0\n"
            "    hooks:\n"
            "      - id: black\n"
        )
        _install(repo, bin_dir)
        assert set(_hooks(repo)) == {"python-fp-lint", "python-fp-lint-check"}
        assert _hooks(repo)["python-fp-lint-check"]["args"] == ["--config", "fp.json"]
        assert (
            "https://github.com/psf/black"
            in (repo / ".pre-commit-config.yaml").read_text()
        )

    def test_reinstalling_does_not_duplicate_hooks(self, repo, bin_dir):
        _install(repo, bin_dir)
        before = (repo / ".pre-commit-config.yaml").read_text()
        _install(repo, bin_dir)
        assert (repo / ".pre-commit-config.yaml").read_text() == before


@pytest.fixture
def fake_pre_commit(bin_dir, tmp_path_factory):
    """A `pre-commit` on PATH that logs each invocation instead of running."""
    log = tmp_path_factory.mktemp("log") / "calls"
    script = bin_dir / "pre-commit"
    script.write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
    script.chmod(0o755)
    return log


class TestTracksMain:
    def test_moves_rev_to_the_tip_of_main_before_installing(
        self, repo, bin_dir, fake_pre_commit
    ):
        _install(repo, bin_dir)
        assert fake_pre_commit.read_text().splitlines() == [
            f"autoupdate --bleeding-edge --repo {REPO_URL}",
            "install",
        ]

    def test_a_failed_update_still_installs(self, repo, bin_dir, fake_pre_commit):
        (bin_dir / "pre-commit").write_text(
            f'#!/bin/sh\necho "$*" >> {fake_pre_commit}\n'
            '[ "$1" = autoupdate ] && exit 1\nexit 0\n'
        )
        result = _install(repo, bin_dir)
        assert fake_pre_commit.read_text().splitlines()[-1] == "install"
        assert "could not update rev" in result.stdout


class TestExistingPreCommitConfig:
    ORIGINAL = (
        "# project hooks\n"
        "default_stages: [pre-commit]\n"
        "repos:\n"
        "    # formatting\n"
        "    - repo: https://github.com/psf/black\n"
        "      rev: 24.1.0\n"
        "      hooks:\n"
        "          - id: black\n"
    )

    def test_restores_the_file_byte_for_byte(self, repo, bin_dir):
        config = repo / ".pre-commit-config.yaml"
        config.write_text(self.ORIGINAL)
        _install(repo, bin_dir)
        assert REPO_URL in config.read_text()
        _uninstall(repo, bin_dir)
        assert config.read_text() == self.ORIGINAL

    def test_removes_a_hand_wired_block_between_other_repos(self, repo, bin_dir):
        config = repo / ".pre-commit-config.yaml"
        config.write_text(
            "repos:\n"
            "  - repo: https://github.com/psf/black\n"
            "    rev: 24.1.0\n"
            "    hooks:\n"
            "      - id: black\n"
            "\n"
            f"  - repo: {REPO_URL}\n"
            "    rev: v1.0.0\n"
            "    hooks:\n"
            "      - id: python-fp-lint\n"
            "        args: [--config, fp.json]\n"
            "\n"
            "  - repo: https://github.com/pycqa/isort\n"
            "    rev: 5.13.2\n"
            "    hooks:\n"
            "      - id: isort\n"
        )
        _uninstall(repo, bin_dir)
        assert config.read_text() == (
            "repos:\n"
            "  - repo: https://github.com/psf/black\n"
            "    rev: 24.1.0\n"
            "    hooks:\n"
            "      - id: black\n"
            "\n"
            "  - repo: https://github.com/pycqa/isort\n"
            "    rev: 5.13.2\n"
            "    hooks:\n"
            "      - id: isort\n"
        )

    def test_leaves_an_empty_list_when_other_keys_remain(self, repo, bin_dir):
        config = repo / ".pre-commit-config.yaml"
        config.write_text("default_stages: [pre-commit]\n")
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert config.read_text() == "default_stages: [pre-commit]\nrepos: []\n"


class TestLintConfig:
    def test_keeps_a_customised_config_and_clears_the_rules_dir(self, repo, bin_dir):
        _install(repo, bin_dir)
        path = repo / "fp.json"
        config = json.loads(path.read_text())
        path.write_text(json.dumps({**config, "max_complexity": 7}))
        _uninstall(repo, bin_dir)
        kept = json.loads(path.read_text())
        assert kept["max_complexity"] == 7
        assert kept["lint_rules_dir"] is None

    def test_keeps_a_config_that_predates_the_install(self, repo, bin_dir):
        path = repo / "fp.json"
        path.write_text(json.dumps({"ast_grep_rules": ["no-list-append"]}))
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert json.loads(path.read_text()) == {
            "ast_grep_rules": ["no-list-append"],
            "lint_rules_dir": None,
        }

    def test_leaves_a_rules_dir_pointing_elsewhere_alone(self, repo, bin_dir):
        _install(repo, bin_dir)
        path = repo / "fp.json"
        config = json.loads(path.read_text())
        path.write_text(json.dumps({**config, "lint_rules_dir": "my-rules"}))
        _uninstall(repo, bin_dir)
        assert json.loads(path.read_text())["lint_rules_dir"] == "my-rules"
