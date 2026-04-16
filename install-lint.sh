#!/bin/sh
# install-lint.sh — python-fp-lint PreToolUse gate installer.
# Installs the lint-check hook that blocks Edit/Write introducing new FP violations.
# Run from the root of the project you want to wire (it must have a .claude/ directory).
# Requires: jq, python-fp-lint (uv run python -m python_fp_lint)

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
SETTINGS="$PROJECT_DIR/.claude/settings.json"

# --- validate ---
if ! command -v jq > /dev/null 2>&1; then
  echo "Error: jq is required but not found." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR/.claude" ]; then
  echo "Error: no .claude/ directory found in $PROJECT_DIR. Run from a Claude Code project root." >&2
  exit 1
fi

# --- install hook ---
echo "Installing lint-check hook..."
mkdir -p ~/.claude/plugins/python-fp-lint/hooks/lib
cp "$PLUGIN_DIR/hooks/lib/hash.sh" ~/.claude/plugins/python-fp-lint/hooks/lib/
cp "$PLUGIN_DIR/hooks/lint-check.sh" ~/.claude/plugins/python-fp-lint/hooks/
chmod +x ~/.claude/plugins/python-fp-lint/hooks/lint-check.sh

# --- install CLI ---
echo "Installing lint CLI..."
mkdir -p ~/.claude/plugins/python-fp-lint/bin
cp "$PLUGIN_DIR/bin/lint" ~/.claude/plugins/python-fp-lint/bin/
chmod +x ~/.claude/plugins/python-fp-lint/bin/lint

# --- install command ---
echo "Installing /lint command..."
mkdir -p ~/.claude/commands
cp "$PLUGIN_DIR/commands/lint.md" ~/.claude/commands/lint.md

# --- create settings.json if missing ---
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
fi

# --- wire Edit hook (idempotent) ---
EDIT_WIRED=$(jq '[.hooks.PreToolUse[]? | select(.matcher == "Edit") | .hooks[]?.command // ""] | any(contains("lint-check"))' "$SETTINGS")
if [ "$EDIT_WIRED" = "false" ]; then
  echo "Wiring Edit PreToolUse hook..."
  HOOK_ENTRY='{"matcher": "Edit", "hooks": [{"type": "command", "command": "~/.claude/plugins/python-fp-lint/hooks/lint-check.sh"}]}'
  jq --argjson entry "$HOOK_ENTRY" \
    '.hooks.PreToolUse = ((.hooks.PreToolUse // []) + [$entry])' \
    "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
else
  echo "Edit hook already wired, skipping."
fi

# --- wire Write hook (idempotent) ---
WRITE_WIRED=$(jq '[.hooks.PreToolUse[]? | select(.matcher == "Write") | .hooks[]?.command // ""] | any(contains("lint-check"))' "$SETTINGS")
if [ "$WRITE_WIRED" = "false" ]; then
  echo "Wiring Write PreToolUse hook..."
  HOOK_ENTRY='{"matcher": "Write", "hooks": [{"type": "command", "command": "~/.claude/plugins/python-fp-lint/hooks/lint-check.sh"}]}'
  jq --argjson entry "$HOOK_ENTRY" \
    '.hooks.PreToolUse = ((.hooks.PreToolUse // []) + [$entry])' \
    "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
else
  echo "Write hook already wired, skipping."
fi

# --- add Bash permissions (idempotent) ---
echo "Adding Bash permissions..."
jq '.permissions.allow = ((.permissions.allow // []) + ["Bash(mkdir:/tmp/ctx-lint)", "Bash(touch:/tmp/ctx-lint/*)", "Bash(rm:/tmp/ctx-lint/)"] | unique)' \
  "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

echo ""
echo "Done. python-fp-lint gate installed for $PROJECT_DIR."
echo "Use /lint to toggle the FP lint gate on/off."
echo "The gate is OFF by default. Enable with: /lint on"
