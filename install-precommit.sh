#!/bin/sh
# install-precommit.sh — wire python-fp-lint into a project's .pre-commit-config.yaml.
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
# Inserted textually rather than via a YAML round-trip, which would drop the
# consumer's comments and reorder their keys.
echo "Wiring python-fp-lint into .pre-commit-config.yaml..."
REPO_URL="$REPO_URL" REV="$REV" LINT_CONFIG="$LINT_CONFIG" CONFIG_YAML="$CONFIG_YAML" \
python3 <<'PY'
import os
import re
import sys

path = os.environ["CONFIG_YAML"]
url = os.environ["REPO_URL"]

try:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
except FileNotFoundError:
    lines = None

CHECK_ID = "python-fp-lint-check"


def hook(pad, hook_id):
    return [
        f"{pad}- id: {hook_id}\n",
        f"{pad}  args: [--config, {os.environ['LINT_CONFIG']}]\n",
    ]


def block(indent):
    pad = " " * indent
    return [
        f"{pad}- repo: {url}\n",
        f"{pad}  rev: {os.environ['REV']}\n",
        f"{pad}  hooks:\n",
        *hook(pad + "    ", "python-fp-lint"),
        *hook(pad + "    ", CHECK_ID),
    ]


def add_check_hook(lines):
    """Append the on-demand hook after the commit hook of an older install."""
    gate_re = re.compile(r"^(\s*)-\s+id:\s*python-fp-lint\s*(#.*)?$")
    found = next(
        ((i, m) for i, m in enumerate(gate_re.match(x) for x in lines) if m), None
    )
    if found is None:
        return None
    at, m = found
    indent = len(m.group(1))
    end = next(
        (
            i
            for i in range(at + 1, len(lines))
            if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent
        ),
        len(lines),
    )
    # Blank lines trailing the hook separate it from what follows; stay above them.
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    return [*lines[:end], *hook(m.group(1), CHECK_ID), *lines[end:]]


if lines is not None and any(url in line for line in lines):
    if any(re.search(rf"id:\s*{CHECK_ID}\b", line) for line in lines):
        print("  already wired, skipping.")
        sys.exit(0)
    out = add_check_hook(lines)
    if out is None:
        print(f"  already wired, but no python-fp-lint hook found; add {CHECK_ID} by hand.")
        sys.exit(0)
    print(f"  already wired, adding the on-demand {CHECK_ID} hook.")
elif lines is None:
    out = ["repos:\n", *block(2)]
else:
    repos_at = next(
        (i for i, line in enumerate(lines) if re.match(r"^repos:\s*$", line)), None
    )
    if repos_at is None:
        # No repos: key -- append one rather than guessing where it belongs.
        tail = "" if not lines or lines[-1].endswith("\n") else "\n"
        out = [*lines, f"{tail}repos:\n", *block(2)]
    else:
        # Insert at the head of the list so the block can't attach itself to a
        # later top-level key, and match the indent the file already uses.
        following = lines[repos_at + 1 :]
        item = next(
            (m for m in (re.match(r"^(\s*)-\s", x) for x in following) if m), None
        )
        indent = len(item.group(1)) if item else 2
        out = [*lines[: repos_at + 1], *block(indent), *following]

with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
print(f"  wrote {path}")
PY

# --- activate ---
if command -v pre-commit > /dev/null 2>&1; then
  echo "Running pre-commit install..."
  pre-commit install
else
  echo ""
  echo "Note: pre-commit is not on PATH. Install it, then run:"
  echo "  pre-commit install"
fi

echo ""
echo "Done. python-fp-lint wired for $PROJECT_DIR."
echo "Rules are configured in $LINT_CONFIG; rule files live in $RULES_DIR/."
echo ""
echo "To lint the working tree without committing:"
echo "  pre-commit run python-fp-lint-check --hook-stage manual --all-files"
echo ""
echo "IMPORTANT: never place a .gitignore inside $RULES_DIR/."
echo "ast-grep silently matches nothing when an ignore file inside the rules"
echo "directory excludes them, so the gate becomes a no-op that still reports"
echo "success. Listing $RULES_DIR/ in the repo's root .gitignore is fine, but"
echo "committing the directory is safer -- CI needs it too."
echo ""
echo "Note: rev is '$REV', a mutable reference. pre-commit clones it once and"
echo "never updates it. Once this repo has tags, change rev in"
echo ".pre-commit-config.yaml or run: pre-commit autoupdate"
