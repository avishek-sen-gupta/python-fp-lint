#!/bin/sh
# uninstall-lint.sh — python-fp-lint PreToolUse gate uninstaller.
# Removes the hook entries from the project's .claude/settings.json,
# deactivates the lint gate for this project, removes the /lint command,
# and removes the plugin directory entirely.
# Run from the root of the project where the gate was installed.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
SETTINGS="$PROJECT_DIR/.claude/settings.json"

# --- validate ---
if ! command -v jq > /dev/null 2>&1; then
  echo "Error: jq is required but not found." >&2
  exit 1
fi

if [ ! -f "$SETTINGS" ]; then
  echo "No .claude/settings.json found in $PROJECT_DIR — nothing to unwire." >&2
fi

# --- deactivate lint gate for this project ---
echo "Deactivating lint gate..."
. "$PLUGIN_DIR/hooks/lib/hash.sh"
LOCK="/tmp/ctx-lint/$(project_hash "$PROJECT_DIR")"
rm -f "$LOCK"

# --- remove hook entries from settings.json ---
if [ -f "$SETTINGS" ]; then
  echo "Removing hook entries from .claude/settings.json..."
  jq 'if .hooks.PreToolUse then
        .hooks.PreToolUse = [
          .hooks.PreToolUse[] |
          select(
            (.hooks // [] | map(.command // "") | any(contains("lint-check"))) | not
          )
        ]
      else . end' \
    "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

  # Remove Bash permissions added by install
  jq '.permissions.allow = ((.permissions.allow // []) | map(select(
        (contains("ctx-lint") | not)
      )))' \
    "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
fi

# --- remove /lint command ---
echo "Removing /lint command..."
rm -f ~/.claude/commands/lint.md

# --- remove plugin directory ---
echo "Removing plugin directory..."
rm -rf ~/.claude/plugins/python-fp-lint

echo ""
echo "Done. python-fp-lint gate uninstalled from $PROJECT_DIR."
