#!/bin/sh
# uninstall-precommit-pyright.sh — undo install-precommit-pyright.sh.
# Run from the root of the project where Pyright was wired.
# Requires: python3.
#
# Does NOT run `pre-commit uninstall`: the git hook it installed drives every
# hook in .pre-commit-config.yaml, not just this one.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/RobertCraigie/pyright-python"
PYRIGHT_CONFIG="pyrightconfig.json"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

# --- unwire .pre-commit-config.yaml ---
# Removed textually, mirroring the installer, so the consumer's comments and
# key order survive.
echo "Unwiring Pyright from .pre-commit-config.yaml..."
unwire_hooks "$CONFIG_YAML" "$REPO_URL"

# --- unwind pyrightconfig.json ---
# Deleted only when it is exactly what the installer seeded; anything else is
# the user's own settings, and a type-checker config is worth more than the
# tidiness of removing it.
echo "Checking $PYRIGHT_CONFIG..."
PYRIGHT_CONFIG="$PROJECT_DIR/$PYRIGHT_CONFIG" \
EXAMPLE="$PLUGIN_DIR/installer/pyrightconfig.example.json" python3 <<'PY'
import json
import os
import sys

path = os.environ["PYRIGHT_CONFIG"]

try:
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
except FileNotFoundError:
    print("  not present, skipping.")
    sys.exit(0)
except json.JSONDecodeError:
    print(f"  {path} is not valid JSON, leaving it alone.")
    sys.exit(0)

with open(os.environ["EXAMPLE"], encoding="utf-8") as f:
    seeded = json.load(f)

if config == seeded:
    os.remove(path)
    print(f"  removed {path}")
else:
    print(f"  {path} has local changes, kept it.")
PY

echo ""
echo "Done. Pyright unwired from $PROJECT_DIR."
echo "The pre-commit git hook is left in place: it runs your other hooks too."
echo "If Pyright was your only hook, run: pre-commit uninstall"
