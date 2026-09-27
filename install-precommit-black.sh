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
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/psf/black"
# A real tag, so the wiring works offline; `pre-commit autoupdate` below moves
# it to whatever the latest release is. Black's tags carry no `v` prefix.
REV="26.5.1"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

# --- wire .pre-commit-config.yaml (idempotent) ---
# Textual, not a YAML round-trip, so the consumer's comments and key
# order survive -- see installer/precommit_yaml.py.
echo "Wiring Black into .pre-commit-config.yaml..."
# stages is explicit rather than left to pre-commit's default. A hook that
# omits it runs at *every* installed stage, so in a repo that also installs a
# commit-msg hook Black would reformat the same staged files a second time per
# commit. Scoped to this hook, not set as the consumer's default_stages: their
# other hooks are not ours to re-stage.
wire_hooks "$CONFIG_YAML" "$REPO_URL" "$REV" \
  '[{"id": "black", "stages": ["pre-commit"]}]'

# --- activate, on the latest release ---
# No --bleeding-edge here, unlike the lint installer: that one tracks this
# project's `main` branch, while Black ships release tags.
UPDATE_CMD="$(autoupdate_cmd "$REPO_URL")"
activate_pre_commit "$UPDATE_CMD" "$REV" "the latest release"

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
