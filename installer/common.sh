# installer/common.sh — scaffolding shared by the install/uninstall scripts.
#
# Sourced, never executed. A caller sets PLUGIN_DIR first, then:
#
#   . "$PLUGIN_DIR/installer/common.sh"
#
# Everything here is POSIX sh, like the scripts that source it.

# Exit 1 unless python3 is on PATH. Every script needs it: the shared
# .pre-commit-config.yaml editor is a Python program.
require_python3() {
  if ! command -v python3 > /dev/null 2>&1; then
    echo "Error: python3 is required but not found." >&2
    exit 1
  fi
}

# Exit 1 unless $1 is the root of a git work tree. Checked rather than
# discovered: these scripts write files whose paths are relative to the root,
# so running one from a subdirectory would scatter them.
require_git_root() {
  if [ ! -d "$1/.git" ]; then
    echo "Error: $1 is not a git repository root." >&2
    exit 1
  fi
}

# Echo the `pre-commit autoupdate` invocation for a repo: autoupdate_cmd URL [FLAG].
#
# Scoped with --repo deliberately. A bare `pre-commit autoupdate` moves *every*
# repo in the consumer's config, which is not ours to do.
autoupdate_cmd() {
  if [ -n "${2:-}" ]; then
    echo "pre-commit autoupdate $2 --repo $1"
  else
    echo "pre-commit autoupdate --repo $1"
  fi
}

# Pin the rev and install the git hook: activate_pre_commit UPDATE_CMD REV WHAT
#
# WHAT names what the rev is being moved to, for the progress line. A failed
# update is a warning rather than a failure: the wiring is already written and
# the pinned rev still works, so there is no reason to leave the install half
# done because the network was unavailable.
activate_pre_commit() {
  _update="$1"
  _rev="$2"
  _what="$3"

  if command -v pre-commit > /dev/null 2>&1; then
    echo "Pinning rev to $_what..."
    if ! $_update; then
      echo "Warning: could not update rev (offline?); it stays '$_rev' for now."
      echo "Re-run this script, or: $_update"
    fi
    echo "Running pre-commit install..."
    pre-commit install
  else
    echo ""
    echo "Note: pre-commit is not on PATH. Install it, then run:"
    echo "  $_update"
    echo "  pre-commit install"
  fi
}

# Add or remove this tool's block in the project's .pre-commit-config.yaml.
# Both delegate to installer/precommit_yaml.py, which edits the file textually
# rather than round-tripping it through a YAML parser -- a round-trip would
# drop the consumer's comments and reorder their keys.
#
#   wire_hooks   CONFIG_YAML URL REV HOOKS_JSON
#   unwire_hooks CONFIG_YAML URL
wire_hooks() {
  python3 "$PLUGIN_DIR/installer/precommit_yaml.py" insert \
    --config "$1" --url "$2" --rev "$3" --hooks "$4"
}

unwire_hooks() {
  python3 "$PLUGIN_DIR/installer/precommit_yaml.py" remove \
    --config "$1" --url "$2"
}
