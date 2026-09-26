# tests/test_precommit_black_installer.py
"""Round-trip tests for install/uninstall-precommit-black.sh."""

import os
import re
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
INSTALL = os.path.join(REPO_ROOT, "install-precommit-black.sh")
UNINSTALL = os.path.join(REPO_ROOT, "uninstall-precommit-black.sh")
BLACK_URL = "https://github.com/psf/black"
LINT_URL = "https://github.com/avishek-sen-gupta/python-fp-lint"
PYRIGHT_URL = "https://github.com/RobertCraigie/pyright-python"


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


def _block(repo):
    config = yaml.safe_load((repo / ".pre-commit-config.yaml").read_text())
    (ours,) = [r for r in config["repos"] if r["repo"] == BLACK_URL]
    return ours


class TestFreshRepo:
    def test_wires_one_blocking_hook(self, repo, bin_dir):
        _install(repo, bin_dir)
        (hook,) = _block(repo)["hooks"]
        assert hook["id"] == "black"
        # No `stages:` key at all -- pre-commit's default is the commit stage.
        assert "stages" not in hook

    def test_pins_a_real_release_tag(self, repo, bin_dir):
        """Black tags carry no `v` prefix, unlike pyright-python's."""
        _install(repo, bin_dir)
        assert re.fullmatch(r"\d+\.\d+\.\d+", str(_block(repo)["rev"]))

    def test_removes_everything_the_installer_created(self, repo, bin_dir):
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [".git"]

    def test_is_a_no_op_when_nothing_is_installed(self, repo, bin_dir):
        _uninstall(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [".git"]

    def test_running_uninstall_twice_is_harmless(self, repo, bin_dir):
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [".git"]

    def test_reinstalling_does_not_duplicate_the_hook(self, repo, bin_dir):
        _install(repo, bin_dir)
        before = (repo / ".pre-commit-config.yaml").read_text()
        _install(repo, bin_dir)
        assert (repo / ".pre-commit-config.yaml").read_text() == before

    def test_refuses_outside_a_git_repo_root(self, tmp_path, bin_dir):
        result = _sh(INSTALL, tmp_path, bin_dir)
        assert result.returncode == 1
        assert "not a git repository root" in result.stderr


class TestSeedsNoConfig:
    """Black's premise is having no settings; the installer writes none."""

    PYPROJECT = '[project]\nname = "thing"\nversion = "0.1.0"\n'

    def test_creates_no_config_file_of_its_own(self, repo, bin_dir):
        _install(repo, bin_dir)
        assert sorted(p.name for p in repo.iterdir()) == [
            ".git",
            ".pre-commit-config.yaml",
        ]

    def test_leaves_an_existing_pyproject_alone(self, repo, bin_dir):
        (repo / "pyproject.toml").write_text(self.PYPROJECT)
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert (repo / "pyproject.toml").read_text() == self.PYPROJECT


class TestExistingPreCommitConfig:
    ORIGINAL = (
        "# project hooks\n"
        "default_stages: [pre-commit]\n"
        "repos:\n"
        "    # linting\n"
        "    - repo: https://github.com/pycqa/isort\n"
        "      rev: 5.13.2\n"
        "      hooks:\n"
        "          - id: isort\n"
    )

    def test_restores_the_file_byte_for_byte(self, repo, bin_dir):
        config = repo / ".pre-commit-config.yaml"
        config.write_text(self.ORIGINAL)
        _install(repo, bin_dir)
        assert BLACK_URL in config.read_text()
        _uninstall(repo, bin_dir)
        assert config.read_text() == self.ORIGINAL


class TestCoexistsWithTheOtherGates:
    """All three installers edit the same file and must not disturb each other."""

    LINT = os.path.join(REPO_ROOT, "install-precommit-lint.sh")
    PYRIGHT = os.path.join(REPO_ROOT, "install-precommit-pyright.sh")

    def _urls(self, repo):
        config = yaml.safe_load((repo / ".pre-commit-config.yaml").read_text())
        return {r["repo"] for r in config["repos"]}

    def test_all_three_can_be_wired(self, repo, bin_dir):
        for script in (self.LINT, self.PYRIGHT):
            assert _sh(script, repo, bin_dir).returncode == 0
        _install(repo, bin_dir)
        assert self._urls(repo) == {LINT_URL, PYRIGHT_URL, BLACK_URL}

    def test_removing_black_leaves_the_others(self, repo, bin_dir):
        for script in (self.LINT, self.PYRIGHT):
            assert _sh(script, repo, bin_dir).returncode == 0
        _install(repo, bin_dir)
        _uninstall(repo, bin_dir)
        assert self._urls(repo) == {LINT_URL, PYRIGHT_URL}
        assert (repo / "pyrightconfig.json").exists()
        assert (repo / "fp.json").exists()


@pytest.fixture
def fake_pre_commit(bin_dir, tmp_path_factory):
    """A `pre-commit` on PATH that logs each invocation instead of running."""
    log = tmp_path_factory.mktemp("log") / "calls"
    script = bin_dir / "pre-commit"
    script.write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
    script.chmod(0o755)
    return log


class TestPinsTheLatestRelease:
    def test_updates_to_the_latest_tag_then_installs(
        self, repo, bin_dir, fake_pre_commit
    ):
        _install(repo, bin_dir)
        assert fake_pre_commit.read_text().splitlines() == [
            f"autoupdate --repo {BLACK_URL}",
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
