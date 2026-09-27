# tests/test_fixture_isolation.py
"""The suite must act on its own fixtures, not on the repo being committed.

Git exports GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and GIT_AUTHOR_* to every
hook it runs, and those take precedence over a subprocess `cwd=`. So a test
that shells out to git while the suite itself runs inside a pre-commit hook
acts on the repo under commit: `git init <tmp_path>` initialises GIT_DIR and
leaves tmp_path without a .git at all, and `git add` stages into the real
index. Both silently, exit 0.

These tests run a slice of the suite under exactly that leaked environment.
"""

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))

SLICES = [
    "tests/test_precommit_black_installer.py::TestFreshRepo::test_wires_one_blocking_hook",
    "tests/test_precommit_pyright_installer.py::TestFreshRepo::test_wires_one_blocking_hook",
    "tests/test_precommit_lint_installer.py::TestInstallWiresBothHooks",
    "tests/test_cli.py::TestPrecommitRatchet",
    "tests/test_ratchet.py::TestVerdict",
]


@pytest.fixture
def leaked_git_env(tmp_path):
    """A decoy repo, plus the environment git hands its hooks, pointing at it."""
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q", "--template=", str(decoy)], check=True)
    env = {
        **os.environ,
        "GIT_DIR": str(decoy / ".git"),
        "GIT_WORK_TREE": str(decoy),
        "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
        "GIT_AUTHOR_NAME": "hook",
        "GIT_AUTHOR_EMAIL": "hook@example.com",
    }
    return decoy, env


def _staged(repo):
    return subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()


@pytest.mark.parametrize("slice_", SLICES)
def test_passes_under_a_leaked_git_environment(slice_, leaked_git_env):
    _, env = leaked_git_env
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", slice_],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:]


def test_stages_nothing_in_the_repo_git_points_at(leaked_git_env):
    """The destructive half: the ratchet tests run `git add`.

    A vacuous pass is the danger here -- a slice that collects nothing stages
    nothing -- so this asserts the inner run actually collected tests.
    """
    decoy, env = leaked_git_env
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *SLICES],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "no tests ran" not in result.stdout, result.stdout[-2000:]
    assert _staged(decoy) == [], result.stdout[-2000:]
