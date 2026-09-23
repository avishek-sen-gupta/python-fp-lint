#!/bin/sh
# uninstall-precommit.sh — undo install-precommit.sh.
# Run from the root of the project where the gate was wired.
# Requires: python3.
#
# Does NOT run `pre-commit uninstall`: the git hook it installed drives every
# hook in .pre-commit-config.yaml, not just this one.

set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$PWD"
CONFIG_YAML="$PROJECT_DIR/.pre-commit-config.yaml"
REPO_URL="https://github.com/avishek-sen-gupta/python-fp-lint"
LINT_CONFIG="fp.json"
RULES_DIR=".python-fp-lint"

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
echo "Unwiring python-fp-lint from .pre-commit-config.yaml..."
REPO_URL="$REPO_URL" CONFIG_YAML="$CONFIG_YAML" python3 <<'PY'
import os
import re
import sys

path = os.environ["CONFIG_YAML"]
url = re.escape(os.environ["REPO_URL"])
item_re = re.compile(rf"^(\s*)-\s+repo:\s*['\"]?{url}(\.git)?['\"]?\s*(#.*)?$")

try:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
except FileNotFoundError:
    print("  no .pre-commit-config.yaml, skipping.")
    sys.exit(0)

match = next(
    ((i, m) for i, m in enumerate(item_re.match(x) for x in lines) if m), None
)
if match is None:
    print("  not wired, skipping.")
    sys.exit(0)

start, m = match
indent = len(m.group(1))


def in_block(line):
    return not line.strip() or len(line) - len(line.lstrip()) > indent


# The block runs until the first non-blank line at or left of the item's dash.
# Trailing blank lines go with it, so a separator isn't left doubled up.
end = next(
    (i for i in range(start + 1, len(lines)) if not in_block(lines[i])), len(lines)
)
out = [*lines[:start], *lines[end:]]

if any(re.match(r"^\s*-\s+repo:", x) for x in out):
    pass
elif all(
    not x.strip() or x.lstrip().startswith("#") or re.match(r"^repos:\s*$", x)
    for x in out
):
    # Nothing left but an empty `repos:` -- the installer created this file.
    os.remove(path)
    print(f"  removed {path}")
    sys.exit(0)
else:
    # A bare `repos:` is null, which pre-commit rejects; keep it a list.
    out = ["repos: []\n" if re.match(r"^repos:\s*$", x) else x for x in out]

with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
print(f"  wrote {path}")
PY

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
