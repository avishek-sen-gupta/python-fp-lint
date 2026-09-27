# tests/gitenv.py
"""Subprocess environments for the fixture repos.

Git exports its own variables to every hook it runs: GIT_DIR, GIT_WORK_TREE,
GIT_INDEX_FILE (relative to the hook's working directory), GIT_AUTHOR_*,
GIT_CONFIG_PARAMETERS. They take precedence over a subprocess `cwd=`, so a test
that shells out to git while the suite itself runs inside a pre-commit hook acts
on the repo being committed rather than on its own tmp_path fixture. Two ways it
bites, both silent and both exit 0:

  git init -q --template= <tmp_path>   initialises GIT_DIR instead, and
                                      tmp_path is left with no .git at all
  git add <file>                       stages into the real repo's index

python-fp-lint's own gate runs in exactly that position, and its tests stage
files, so the fixtures scrub the environment instead of trusting cwd. The
production code is deliberately untouched: `python-fp-lint precommit` *is* the
hook, and it should read the GIT_* vars git hands it.

GIT_EXEC_PATH is kept: it locates git's own helper binaries and redirects
nothing.

Imported as `from gitenv import clean_env` -- tests/ is not a package, so pytest
puts this directory on sys.path rather than the repo root.
"""

import os

KEEP = {"GIT_EXEC_PATH"}


def clean_env(**overrides: str) -> dict:
    """os.environ with git's redirecting variables removed, plus any overrides."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") or key in KEEP
    }
    env.update(overrides)
    return env
