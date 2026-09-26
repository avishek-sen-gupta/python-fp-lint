#!/bin/sh
# install-precommit-lint.sh — wire python-fp-lint into a project's .pre-commit-config.yaml.
# Run from the root of the project you want to gate.
# Requires: python3, and `pre-commit` on PATH for the final install step.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/avishek-sen-gupta/python-fp-lint"
LINT_CONFIG="fp.json"
RULES_DIR=".python-fp-lint"
REV="main"

# --- validate ---
if ! command -v python3 > /dev/null 2>&1; then
  echo "Error: python3 is required but not found." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.git" ]; then
  echo "Error: $PROJECT_DIR is not a git repository root." >&2
  exit 1
fi

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
# The edit is textual rather than a YAML round-trip, which would drop the
# consumer's comments and reorder their keys. installer/precommit_yaml.py
# holds that logic; the Pyright installer wires its own hook the same way.
echo "Wiring python-fp-lint into .pre-commit-config.yaml..."
python3 "$PLUGIN_DIR/installer/precommit_yaml.py" insert \
  --config "$CONFIG_YAML" \
  --url "$REPO_URL" \
  --rev "$REV" \
  --hooks "[{\"id\": \"python-fp-lint\", \"args\": [\"--config\", \"$LINT_CONFIG\"]},
            {\"id\": \"python-fp-lint-check\", \"args\": [\"--config\", \"$LINT_CONFIG\"]}]"

# --- activate, tracking main ---
# pre-commit never re-fetches a branch name: `rev: main` is cloned once and
# frozen. Tracking main means rewriting rev to main's current SHA, which is
# what --bleeding-edge does; each re-run of this script moves it forward.
UPDATE_CMD="pre-commit autoupdate --bleeding-edge --repo $REPO_URL"
if command -v pre-commit > /dev/null 2>&1; then
  echo "Pinning rev to the tip of main..."
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
