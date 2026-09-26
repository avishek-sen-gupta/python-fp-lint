#!/bin/sh
# install-precommit-pyright.sh — wire Pyright into a project's .pre-commit-config.yaml.
# Run from the root of the project you want to gate.
# Requires: python3, and `pre-commit` on PATH for the final install step.
#
# The hook is a blocking one: it runs at the commit stage, and strict mode on
# a codebase that has never been type-checked will have plenty to say. There
# is no ratchet for Pyright -- its findings are not part of python-fp-lint's
# violation total -- so a repo that cannot pass strict cannot commit until it
# does. That is the deal; `uninstall-precommit-pyright.sh` backs it out.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/RobertCraigie/pyright-python"
PYRIGHT_CONFIG="pyrightconfig.json"
# A real tag, so the wiring works offline; `pre-commit autoupdate` below moves
# it to whatever the latest release is.
REV="v1.1.414"

# --- validate ---
if ! command -v python3 > /dev/null 2>&1; then
  echo "Error: python3 is required but not found." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "Error: $PROJECT_DIR is not a git repository root." >&2
  exit 1
fi

# --- seed pyrightconfig.json ---
# Deliberately minimal. No `include`, so Pyright scans the whole repo and the
# file stays layout-agnostic -- its own defaults already skip node_modules,
# __pycache__ and dotted directories. No `pythonVersion` either: this repo's
# floor is not the consumer's, and pinning ours would flag their valid code.
if [ -f "$PROJECT_DIR/$PYRIGHT_CONFIG" ]; then
  echo "Config $PYRIGHT_CONFIG already exists, leaving it as it is."
else
  echo "Creating $PYRIGHT_CONFIG (strict)..."
  cp "$PLUGIN_DIR/installer/pyrightconfig.example.json" \
     "$PROJECT_DIR/$PYRIGHT_CONFIG"
fi

# --- wire .pre-commit-config.yaml (idempotent) ---
# The edit is textual rather than a YAML round-trip, which would drop the
# consumer's comments and reorder their keys. installer/precommit_yaml.py
# holds that logic, shared with the lint installer.
#
# The hook carries no `stages:` key: pre-commit's default is the commit stage,
# which is what makes this gate block.
echo "Wiring Pyright into .pre-commit-config.yaml..."
python3 "$PLUGIN_DIR/installer/precommit_yaml.py" insert \
  --config "$CONFIG_YAML" \
  --url "$REPO_URL" \
  --rev "$REV" \
  --hooks '[{"id": "pyright"}]'

# --- activate, on the latest release ---
# No --bleeding-edge here, unlike the lint installer: that one tracks this
# project's `main` branch, while pyright-python ships release tags.
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
echo "Done. Pyright wired for $PROJECT_DIR, in strict mode."
echo ""
echo "See what it says before your next commit:"
echo "  pre-commit run pyright --all-files"
echo ""
echo "$PYRIGHT_CONFIG resolves imports from .venv; if this project keeps its"
echo "environment elsewhere, edit venvPath/venv to match. Pyright warns and"
echo "carries on when the path is missing, so a fresh clone is not blocked."
echo ""
echo "Strict is strict. To soften it while you burn the count down, set"
echo "typeCheckingMode to \"standard\" or \"basic\" in $PYRIGHT_CONFIG, or"
echo "switch individual reportUnknown* rules to \"warning\"."
