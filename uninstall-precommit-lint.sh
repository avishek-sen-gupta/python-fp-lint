#!/bin/sh
# uninstall-precommit-lint.sh — undo install-precommit-lint.sh.
# Run from the root of the project where the gate was wired.
# Requires: python3.
#
# Does NOT run `pre-commit uninstall`: the git hook it installed drives every
# hook in .pre-commit-config.yaml, not just this one.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/avishek-sen-gupta/python-fp-lint"
LINT_CONFIG="fp.json"
RULES_DIR=".python-fp-lint"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

# --- unwire .pre-commit-config.yaml ---
# Removed textually, mirroring the installer, so the consumer's comments and
# key order survive.
echo "Unwiring python-fp-lint from .pre-commit-config.yaml..."
unwire_hooks "$CONFIG_YAML" "$REPO_URL"

# --- remove the copied ast-grep rules ---
if [ -d "$PROJECT_DIR/$RULES_DIR" ]; then
  echo "Removing $RULES_DIR/..."
  rm -rf "${PROJECT_DIR:?}/$RULES_DIR"
fi

# --- unwind the lint config ---
# Deleted only when it is exactly what the installer seeded; otherwise it may
# hold the user's own settings, so only the installer's lint_rules_dir goes.
LINT_CONFIG="$PROJECT_DIR/$LINT_CONFIG" RULES_DIR="$RULES_DIR" \
EXAMPLE="$PLUGIN_DIR/config.example.json" python3 <<'PY'
import json
import os
import sys

path = os.environ["LINT_CONFIG"]
rules_dir = os.environ["RULES_DIR"]

try:
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
except FileNotFoundError:
    sys.exit(0)

if config.get("lint_rules_dir") != rules_dir:
    print(f"  {path}: lint_rules_dir not set by the installer, leaving it alone.")
    sys.exit(0)

with open(os.environ["EXAMPLE"], encoding="utf-8") as f:
    seeded = {**json.load(f), "lint_rules_dir": rules_dir}

if config == seeded:
    os.remove(path)
    print(f"  removed {path}")
    sys.exit(0)

with open(path, "w", encoding="utf-8") as f:
    json.dump({**config, "lint_rules_dir": None}, f, indent=2)
    f.write("\n")
print(f"  {path} has local changes, kept it and cleared lint_rules_dir.")
PY

echo ""
echo "Done. python-fp-lint unwired from $PROJECT_DIR."
echo "The pre-commit git hook is left in place: it runs your other hooks too."
echo "If python-fp-lint was your only hook, run: pre-commit uninstall"
