#!/bin/sh
# install-precommit-lint.sh — wire python-fp-lint into a project's .pre-commit-config.yaml.
# Run from the root of the project you want to gate.
# Requires: python3, and `pre-commit` on PATH for the final install step.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$PLUGIN_DIR/installer/common.sh"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/avishek-sen-gupta/python-fp-lint"
LINT_CONFIG="fp.json"
RULES_DIR=".python-fp-lint"
REV="main"

# --- validate ---
require_python3
require_git_root "$PROJECT_DIR"

# --- copy the ast-grep rules into the repo ---
# They live here rather than inside the installed package because ast-grep
# silently matches nothing for rule files under a gitignored path, and the
# package normally lands in .venv, which is gitignored.
echo "Copying ast-grep rules into $RULES_DIR/..."
rm -rf "${PROJECT_DIR:?}/$RULES_DIR"
mkdir -p "$PROJECT_DIR/$RULES_DIR"
cp "$PLUGIN_DIR/python_fp_lint/sgconfig.yml" "$PROJECT_DIR/$RULES_DIR/"
cp -R "$PLUGIN_DIR/python_fp_lint/rules" "$PROJECT_DIR/$RULES_DIR/"

# --- seed the lint config ---
if [ -f "$PROJECT_DIR/$LINT_CONFIG" ]; then
  echo "Config $LINT_CONFIG already exists, pointing lint_rules_dir at $RULES_DIR."
else
  echo "Creating $LINT_CONFIG from config.example.json..."
  cp "$PLUGIN_DIR/config.example.json" "$PROJECT_DIR/$LINT_CONFIG"
fi

# lint_rules_dir is relative to the config file, which sits at the repo root.
LINT_CONFIG="$PROJECT_DIR/$LINT_CONFIG" RULES_DIR="$RULES_DIR" python3 <<'PY'
import json
import os

path = os.environ["LINT_CONFIG"]
with open(path, encoding="utf-8") as f:
    config = json.load(f)
config["lint_rules_dir"] = os.environ["RULES_DIR"]
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PY

# --- wire .pre-commit-config.yaml (idempotent) ---
# Textual, not a YAML round-trip, so the consumer's comments and key
# order survive -- see installer/precommit_yaml.py.
echo "Wiring python-fp-lint into .pre-commit-config.yaml..."
wire_hooks "$CONFIG_YAML" "$REPO_URL" "$REV" "[{\"id\": \"python-fp-lint\", \"args\": [\"--config\", \"$LINT_CONFIG\"]},
            {\"id\": \"python-fp-lint-check\", \"args\": [\"--config\", \"$LINT_CONFIG\"]}]"

# --- activate, tracking main ---
# pre-commit never re-fetches a branch name: `rev: main` is cloned once and
# frozen. Tracking main means rewriting rev to main's current SHA, which is
# what --bleeding-edge does; each re-run of this script moves it forward.
UPDATE_CMD="$(autoupdate_cmd "$REPO_URL" --bleeding-edge)"
activate_pre_commit "$UPDATE_CMD" "$REV" "the tip of main"

echo ""
echo "Done. python-fp-lint wired for $PROJECT_DIR."
echo "Rules are configured in $LINT_CONFIG; rule files live in $RULES_DIR/."
echo ""
echo "To lint the working tree without committing:"
echo "  pre-commit run python-fp-lint-check --hook-stage manual --all-files"
echo ""
echo "To move to the latest python-fp-lint main later, re-run this script or:"
echo "  $UPDATE_CMD"
echo ""
echo "IMPORTANT: never place a .gitignore inside $RULES_DIR/."
echo "ast-grep silently matches nothing when an ignore file inside the rules"
echo "directory excludes them, so the gate becomes a no-op that still reports"
echo "success. Listing $RULES_DIR/ in the repo's root .gitignore is fine, but"
echo "committing the directory is safer -- CI needs it too."
