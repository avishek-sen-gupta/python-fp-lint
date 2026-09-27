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
# WHAT names what the rev is being moved to, for the progress line.
#
# Nothing here is fatal, and that is deliberate. The wiring is already written
# by the time this runs, and it is useful on its own -- CI runs `pre-commit run`
# without any git hook installed. So every way this can fail ends in a warning
# that says "hooks NOT activated" and names the command to finish the job, and
# the caller goes on to print its own closing guidance.
#
# It used to end in `pre-commit install` bare. Under `set -e` a non-zero exit
# there killed the installer on the spot -- past the point where the config was
# written, before any of the guidance -- so a consumer with core.hooksPath set
# got pre-commit's refusal, exit 1, a wired config, no git hook and no idea
# which of those were true.
activate_pre_commit() {
  _update="$1"
  _rev="$2"
  _what="$3"

  if ! command -v pre-commit > /dev/null 2>&1; then
    echo ""
    echo "Note: hooks NOT activated -- pre-commit is not on PATH."
    echo "Install it, then run:"
    echo "  $_update"
    echo "  pre-commit install"
    return 0
  fi

  echo "Pinning rev to $_what..."
  # A failed update is a warning, not a failure: the pinned rev still works, so
  # there is no reason to stop because the network was unavailable.
  if ! $_update; then
    echo "Warning: could not update rev (offline?); it stays '$_rev' for now."
    echo "Re-run this script, or: $_update"
  fi

  # `git config --get` exits 1 when the key is unset -- the common case -- so
  # `|| true` keeps `set -e` from killing the script on the happy path.
  _hooks_path="$(git config --get core.hooksPath || true)"
  if [ -n "$_hooks_path" ]; then
    echo ""
    echo "Warning: hooks NOT activated. core.hooksPath is set to"
    echo "  $_hooks_path"
    echo "so pre-commit refuses to install, and git will not run anything from"
    echo ".git/hooks. The setting is left exactly as it is -- it is yours, and"
    echo "whether to drop it is not an installer's call. To activate the hook,"
    echo "either remove it:"
    echo "  git config --unset core.hooksPath   # --global if it is set globally"
    echo "  pre-commit install"
    echo "or make the hooks in $_hooks_path call pre-commit themselves."
    return 0
  fi

  echo "Running pre-commit install..."
  if ! pre-commit install; then
    echo ""
    echo "Warning: hooks NOT activated -- 'pre-commit install' failed above."
    echo "The wiring is written, so CI can still run these hooks. To activate"
    echo "the git hook, fix whatever it reported and run:"
    echo "  pre-commit install"
  fi
  return 0
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
