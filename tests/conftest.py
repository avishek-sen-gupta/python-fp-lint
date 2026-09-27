# tests/conftest.py
"""Make the whole suite hermetic against git's hook environment.

The per-call `env=clean_env()` in the fixtures covers what the tests hand to a
subprocess. It cannot cover the production code the tests call *in process* --
`ratchet` shells out to `git add` itself, and that inherits pytest's own
environment. So the GIT_* variables are stripped once, for the session.

Only the tests are made hermetic. Production stays as it is on purpose: a
pre-commit hook is *supposed* to read the GIT_DIR and GIT_INDEX_FILE git hands
it, which is how the gate sees the staged index rather than the worktree.

See gitenv.py for which variables, and why GIT_EXEC_PATH survives.
"""

import os

import pytest
from gitenv import KEEP


@pytest.fixture(scope="session", autouse=True)
def _hermetic_git_env():
    leaked = [key for key in os.environ if key.startswith("GIT_") and key not in KEEP]
    patch = pytest.MonkeyPatch()
    for key in leaked:
        patch.delenv(key, raising=False)
    yield
    patch.undo()
