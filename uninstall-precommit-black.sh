#!/bin/sh
# uninstall-precommit-black.sh — undo install-precommit-black.sh.
# Run from the root of the project where Black was wired.
# Requires: python3.
#
# Removes the hook only. The installer seeded no config, so there is nothing
# else of ours to take away -- and your files stay formatted, which is the
# point of having run it.
#
# Does NOT run `pre-commit uninstall`: the git hook it installed drives every
# hook in .pre-commit-config.yaml, not just this one.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/psf/black"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

# --- unwire .pre-commit-config.yaml ---
# Removed textually, mirroring the installer, so the consumer's comments and
# key order survive.
echo "Unwiring Black from .pre-commit-config.yaml..."
unwire_hooks "$CONFIG_YAML" "$REPO_URL"

echo ""
echo "Done. Black unwired from $PROJECT_DIR."
echo "Any [tool.black] settings in your pyproject.toml are left alone; the"
echo "installer never wrote them."
echo "The pre-commit git hook is left in place: it runs your other hooks too."
echo "If Black was your only hook, run: pre-commit uninstall"
