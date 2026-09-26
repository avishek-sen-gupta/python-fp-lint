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
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/psf/black"

# --- validate ---
if ! command -v python3 > /dev/null 2>&1; then
  echo "Error: python3 is required but not found." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "Error: $PROJECT_DIR is not a git repository root." >&2
  exit 1
fi

# --- unwire .pre-commit-config.yaml ---
# Removed textually, mirroring the installer, so the consumer's comments and
# key order survive.
echo "Unwiring Black from .pre-commit-config.yaml..."
python3 "$PLUGIN_DIR/installer/precommit_yaml.py" remove \
  --config "$CONFIG_YAML" --url "$REPO_URL"

echo ""
echo "Done. Black unwired from $PROJECT_DIR."
echo "Any [tool.black] settings in your pyproject.toml are left alone; the"
echo "installer never wrote them."
echo "The pre-commit git hook is left in place: it runs your other hooks too."
echo "If Black was your only hook, run: pre-commit uninstall"
