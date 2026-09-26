#!/bin/sh
# install-precommit-black.sh — wire Black into a project's .pre-commit-config.yaml.
# Run from the root of the project you want to format.
# Requires: python3, and `pre-commit` on PATH for the final install step.
#
# Unlike the lint and Pyright gates, this hook *rewrites* your files rather
# than reporting on them. pre-commit treats a hook that modified the worktree
# as a failure, so the first commit after Black reformats something aborts:
# re-stage the reformatted files and commit again. That is the normal Black
# experience, not a fault in this script.
#
# No config file is seeded. Black's premise is not having settings; if you
# want `line-length` or `target-version`, they belong in your own
# pyproject.toml under [tool.black], not in something an installer wrote.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/psf/black"
# A real tag, so the wiring works offline; `pre-commit autoupdate` below moves
# it to whatever the latest release is. Black's tags carry no `v` prefix.
REV="26.5.1"

# --- validate ---
if ! command -v python3 > /dev/null 2>&1; then
  echo "Error: python3 is required but not found." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "Error: $PROJECT_DIR is not a git repository root." >&2
  exit 1
fi

# --- wire .pre-commit-config.yaml (idempotent) ---
# The edit is textual rather than a YAML round-trip, which would drop the
# consumer's comments and reorder their keys. installer/precommit_yaml.py
# holds that logic, shared with the lint and Pyright installers.
echo "Wiring Black into .pre-commit-config.yaml..."
python3 "$PLUGIN_DIR/installer/precommit_yaml.py" insert \
  --config "$CONFIG_YAML" \
  --url "$REPO_URL" \
  --rev "$REV" \
  --hooks '[{"id": "black"}]'

# --- activate, on the latest release ---
# No --bleeding-edge here, unlike the lint installer: that one tracks this
# project's `main` branch, while Black ships release tags.
UPDATE_CMD="pre-commit autoupdate --repo $REPO_URL"
if command -v pre-commit > /dev/null 2>&1; then
  echo "Pinning rev to the latest release..."
  if ! $UPDATE_CMD; then
    echo "Warning: could not update rev (offline?); it stays '$REV' for now."
    echo "Re-run this script, or: $UPDATE_CMD"
  fi
  echo "Running pre-commit install..."
  pre-commit install
else
  echo ""
  echo "Note: pre-commit is not on PATH. Install it, then run:"
  echo "  $UPDATE_CMD"
  echo "  pre-commit install"
fi

echo ""
echo "Done. Black wired for $PROJECT_DIR."
echo ""
echo "Format everything once, before it starts interrupting commits:"
echo "  pre-commit run black --all-files"
echo ""
echo "Black rewrites files, and pre-commit fails a run that changed the"
echo "worktree. So the commit that first reformats a file aborts; re-stage"
echo "and commit again. Running the line above gets that out of the way in"
echo "one go -- and makes a tidy, reviewable 'apply Black' commit."
