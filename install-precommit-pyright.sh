#!/bin/sh
# install-precommit-pyright.sh — wire Pyright into a project's .pre-commit-config.yaml.
# Run from the root of the project you want to gate.
# Requires: python3, and `pre-commit` on PATH for the final install step.
#
# The hook is a blocking one: it runs at the commit stage (and only there --
# the wiring says so explicitly), and strict mode on
# a codebase that has never been type-checked will have plenty to say. There
# is no ratchet for Pyright -- its findings are not part of python-fp-lint's
# violation total -- so a repo that cannot pass strict cannot commit until it
# does. That is the deal; `uninstall-precommit-pyright.sh` backs it out.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/RobertCraigie/pyright-python"
PYRIGHT_CONFIG="pyrightconfig.json"
# A real tag, so the wiring works offline; `pre-commit autoupdate` below moves
# it to whatever the latest release is.
REV="v1.1.414"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

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
# Textual, not a YAML round-trip, so the consumer's comments and key
# order survive -- see installer/precommit_yaml.py.
echo "Wiring Pyright into .pre-commit-config.yaml..."
# stages is explicit rather than left to pre-commit's default. A hook that
# omits it runs at *every* installed stage, so in a repo that also installs a
# commit-msg hook Pyright would type-check twice per commit. Scoped to this
# hook, not set as the consumer's default_stages: their other hooks are not
# ours to re-stage.
wire_hooks "$CONFIG_YAML" "$REPO_URL" "$REV" \
  '[{"id": "pyright", "stages": ["pre-commit"]}]'

# --- activate, on the latest release ---
# No --bleeding-edge here, unlike the lint installer: that one tracks this
# project's `main` branch, while pyright-python ships release tags.
UPDATE_CMD="$(autoupdate_cmd "$REPO_URL")"
activate_pre_commit "$UPDATE_CMD" "$REV" "the latest release"

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
