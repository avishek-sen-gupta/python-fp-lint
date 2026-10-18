# python_fp_lint/lint_gate.py
"""Unified LintGate — runs ast-grep + Ruff + beniget in sequence."""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from python_fp_lint.reassignment_gate import ReassignmentGate

# BackendError lives in result.py so reassignment_gate can raise it without
# importing this module; it stays importable from here.
from python_fp_lint.result import BackendError, LintResult, LintViolation

# Ruff rule selection — batteries-included + FP-specific
_DEFAULT_RUFF_SELECT = "E,F,W,I,B,UP,SIM,RUF,BLE,T20,TID252,C901,PLR0915,PLR0917,ANN401"
_DEFAULT_RUFF_IGNORE = "E501,W292"
# Ruff's C901 ceiling. Deliberately stricter than Ruff's own default of 10:
# a function past three branches is asking to be decomposed.
_DEFAULT_MAX_COMPLEXITY = 3
# Ruff's PLR0915 ceiling, counted in statements rather than physical lines.
# Deliberately stricter than Ruff's own default of 50.
_DEFAULT_MAX_STATEMENTS = 10
# Ruff's PLR0917 ceiling. Keyword-only parameters, *args/**kwargs and a
# method's self/cls are not counted. Deliberately stricter than Ruff's own
# default of 5.
_DEFAULT_MAX_POSITIONAL_ARGS = 4

# Paths per subprocess invocation. A whole-repo scan on a large codebase
# otherwise exceeds ARG_MAX; chunking also bounds each call's work, which is
# what keeps the 30s timeout realistic.
_MAX_PATHS_PER_CALL = 1000


def _chunked(items: Sequence[str], size: int = _MAX_PATHS_PER_CALL) -> list[list[str]]:
    """Split a path list into subprocess-sized batches. Never yields an empty batch."""
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _package_rules_dir() -> str:
    """The rules shipped inside the installed package."""
    return os.path.dirname(os.path.abspath(__file__))


def _default_rules_cache_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".cache", "python_fp_lint", "rules")


@dataclass(frozen=True)
class LintSettings:
    """What the gate enforces, fully resolved: every field holds a real value.

    Build one directly, or from a config file and command-line overrides with
    python_fp_lint.settings (load_settings, resolve_settings). An empty
    ast_grep_rules means no filter: every rule runs.
    """

    ruff_select: str = _DEFAULT_RUFF_SELECT
    ast_grep_rules: Sequence[str] = ()
    exclude: Sequence[str] = ()
    max_complexity: int = _DEFAULT_MAX_COMPLEXITY
    max_statements: int = _DEFAULT_MAX_STATEMENTS
    max_positional_args: int = _DEFAULT_MAX_POSITIONAL_ARGS
    rules_dir: str = field(default_factory=_package_rules_dir)
    rules_cache_root: str = field(default_factory=_default_rules_cache_root)


# The default for LintGate's parameter. Frozen, so one instance is safe to
# share, and named, so the signature carries no call (Ruff B008) and no None.
_DEFAULT_SETTINGS = LintSettings()


class LintGate:
    """Unified lint gate — runs ast-grep, Ruff, and beniget reassignment detection.

    It reads no files to configure itself: everything it enforces arrives in
    `settings`, already resolved.
    """

    def __init__(self, *, settings: LintSettings = _DEFAULT_SETTINGS):
        self.settings = settings

    def evaluate(self, changed_files: Sequence[str], project_root: str) -> LintResult:
        py_files = self.filter_excluded(
            _filter_python_files(changed_files), project_root
        )
        if not py_files:
            return LintResult(passed=True, violations=[])

        violations = [
            *self._run_ast_grep(py_files),
            *self._run_ruff(py_files),
            *self._run_reassignment(py_files, project_root),
        ]

        return LintResult(passed=len(violations) == 0, violations=violations)

    def is_excluded(self, path: str, project_root: str) -> bool:
        """True when path matches one of the configured exclude globs."""
        return is_excluded(path, project_root, self.settings.exclude)

    def filter_excluded(self, files: Sequence[str], project_root: str) -> list[str]:
        """Drop every path matching an exclude glob."""
        patterns = self.settings.exclude
        if not patterns:
            return list(files)
        return [f for f in files if not is_excluded(f, project_root, patterns)]

    def _run_ast_grep(self, files: Sequence[str]) -> list[LintViolation]:
        sg = _find_sg()
        if sg is None:
            return []
        return self._scan(sg, files)

    def _scan(self, sg: str, files: Sequence[str]) -> list[LintViolation]:
        rules_dir = self.settings.rules_dir
        if not os.path.exists(os.path.join(rules_dir, "sgconfig.yml")):
            return []
        # The package copy normally lives in the consumer's .venv, which is
        # gitignored -- and ast-grep silently matches nothing under an ignored
        # path -- so it has to be copied out before scanning. A rules dir the
        # consumer pointed us at is used where it stands.
        scan_dir = (
            _materialize_rules_dir(rules_dir, self.settings.rules_cache_root)
            if os.path.abspath(rules_dir) == _package_rules_dir()
            else rules_dir
        )
        allowed = self.settings.ast_grep_rules
        return [
            v for v in _run_sg(sg, scan_dir, files) if not allowed or v.rule in allowed
        ]

    def _run_ruff(self, files: Sequence[str]) -> list[LintViolation]:
        ruff = _find_ruff()
        if ruff is None:
            return []
        return _run_ruff(
            ruff,
            files,
            self.settings.ruff_select,
            self.settings.max_complexity,
            max_statements=self.settings.max_statements,
            max_positional_args=self.settings.max_positional_args,
        )

    def _run_reassignment(
        self, files: Sequence[str], project_root: str
    ) -> list[LintViolation]:
        result = ReassignmentGate().evaluate(files, project_root)
        return result.violations


# --- shared helpers ---


def _git_visible_files(directory: str) -> list[str] | None:
    """Files under `directory` that git doesn't ignore, tracked or not.

    None when `directory` isn't in a git work tree, or is itself ignored --
    naming an ignored directory explicitly asks for it to be linted.
    """
    try:
        ignored = subprocess.run(
            ["git", "-C", directory, "check-ignore", "-q", "."],
            capture_output=True,
            timeout=30,
        )
        listed = subprocess.run(
            ["git", "-C", directory, "ls-files", "-z", "-co", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ignored.returncode == 0 or listed.returncode != 0:
        return None
    return [os.path.join(directory, f) for f in listed.stdout.split("\0") if f]


def _walk_directory(directory: str) -> list[str]:
    """Every file under `directory`, minus what git ignores inside a repo."""
    visible = _git_visible_files(directory)
    if visible is not None:
        return visible
    return [
        os.path.join(root, f)
        for root, _dirs, files in os.walk(directory)
        for f in files
    ]


def _expand_path(path: str) -> list[str]:
    """One directory, glob or plain file, as the paths it stands for."""
    if os.path.isdir(path):
        return _walk_directory(path)
    if any(c in path for c in ("*", "?", "[")):
        return glob.glob(path, recursive=True)
    return [path]


def _expand_paths(paths: Sequence[str]) -> list[str]:
    """Expand directories, globs, and plain files into a flat list of paths."""
    return [expanded for p in paths for expanded in _expand_path(p)]


def _filter_python_files(files: Sequence[str]) -> list[str]:
    """Expand dirs/globs, then filter to existing, unique .py files.

    dict.fromkeys deduplicates while keeping each path's first position."""
    return [
        real
        for real in dict.fromkeys(os.path.abspath(f) for f in _expand_paths(files))
        if real.endswith(".py") and os.path.exists(real)
    ]


# One token per alternative, longest first, so `**` never splits into two `*`.
_GLOB_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|[^*?]+")

_GLOB_REGEX = {
    "**/": r"(?:.*/)?",
    "**": r".*",
    "*": r"[^/]*",
    "?": r"[^/]",
}


@cache
def _compile_glob(pattern: str) -> re.Pattern:
    """Compile one exclude glob into an anchored regex.

    `*` and `?` stop at a path separator, `**` crosses them, and a trailing
    `/` is shorthand for "everything under this directory".
    """
    body = pattern[:-1] + "/**" if pattern.endswith("/") else pattern
    return re.compile(
        "".join(_GLOB_REGEX.get(t, re.escape(t)) for t in _GLOB_TOKEN.findall(body))
        + r"\Z"
    )


def _relative_path(path: str, project_root: str) -> str:
    """path as a project-relative posix string; absolute if it lies outside."""
    root = os.path.abspath(project_root)
    absolute = os.path.abspath(
        path if os.path.isabs(path) else os.path.join(root, path)
    )
    rel = os.path.relpath(absolute, root)
    chosen = absolute if rel == ".." or rel.startswith(".." + os.sep) else rel
    return chosen.replace(os.sep, "/")


def is_excluded(path: str, project_root: str, patterns: Sequence[str]) -> bool:
    """True when path matches any of the exclude globs.

    Globs are matched against the path relative to project_root. A pattern
    containing no `/` is matched against the basename at any depth, the way
    .gitignore treats a bare name -- so `*_pb2.py` needs no `**/` prefix, and
    a whole directory is excluded by naming it with a slash (`build/`).
    """
    rel = _relative_path(path, project_root)
    base = os.path.basename(rel)
    return any(
        _compile_glob(p).match(base if "/" not in p else rel) is not None
        for p in patterns
    )


def _rules_signature(rules_dir: str) -> str:
    """Content hash of every file under rules_dir, used as its cache key.

    Each file contributes its relative path then its bytes, in sorted order.
    Hashing the joined bytes equals feeding them to update() in turn, so the
    keys of existing cache entries are unchanged."""
    paths = [
        os.path.join(root, name)
        for root, _dirs, files in sorted(os.walk(rules_dir))
        for name in sorted(files)
    ]
    return hashlib.sha256(
        b"".join(
            os.path.relpath(p, rules_dir).encode() + Path(p).read_bytes() for p in paths
        )
    ).hexdigest()


def _materialize_rules_dir(source_dir: str, cache_root: str) -> str:
    """Copy rules_dir to a stable location outside any consumer's git tree.

    ast-grep silently finds zero matches for rule files that live under a
    path excluded by the enclosing git repo's .gitignore -- e.g. a project's
    own .venv, where this package is normally installed -- regardless of
    --no-ignore flags. Scanning always uses a copy under the cache root
    instead, which is never inside a consumer's tree.
    """
    target = os.path.join(cache_root, _rules_signature(source_dir))
    if not os.path.isdir(target):
        _publish_copy(source_dir, cache_root, target)
    return target


def _publish_copy(source_dir: str, root: str, target: str) -> None:
    """Copy into a temp sibling, then rename: a reader never sees half a copy."""
    tmp_target = target + ".tmp"
    if os.path.isdir(tmp_target):
        shutil.rmtree(tmp_target)
    os.makedirs(root, exist_ok=True)
    shutil.copytree(source_dir, tmp_target)
    os.replace(tmp_target, target)


def _which(name: str) -> str | None:
    """Locate a tool on PATH, falling back to the running interpreter's bin dir.

    The fallback matters when python-fp-lint is installed into an isolated
    environment (pre-commit, pipx, uvx): the console script's siblings --
    `ruff`, `ast-grep` -- live next to sys.executable but that directory is
    not necessarily on PATH.
    """
    found = shutil.which(name)
    if found:
        return found
    sibling = os.path.join(os.path.dirname(sys.executable), name)
    return sibling if os.path.isfile(sibling) and os.access(sibling, os.X_OK) else None


def _find_sg() -> str | None:
    return _which("sg") or _which("ast-grep")


def _find_ruff() -> str | None:
    return _which("ruff")


def missing_backends() -> list[str]:
    """External backends that are not reachable, in report-friendly names."""
    return [
        name
        for name, found in (("ast-grep", _find_sg()), ("ruff", _find_ruff()))
        if found is None
    ]


def require_backends() -> None:
    """BackendError when ast-grep or Ruff is unreachable.

    A missing backend contributes zero violations, which must never pass for
    a clean repo -- under the ratchet it would read as an improvement and
    tighten the baseline toward zero.
    """
    missing = missing_backends()
    if missing:
        raise BackendError(f"required lint backend(s) not found: {', '.join(missing)}")


class ConfigError(Exception):
    """An explicitly-specified config file is missing or unreadable."""


def _run_sg_once(
    sg_path: str, rules_dir: str, files: Sequence[str]
) -> list[LintViolation]:
    stdout = _run_backend(
        "ast-grep",
        [
            sg_path,
            "scan",
            "--json",
            "--config",
            os.path.join(rules_dir, "sgconfig.yml"),
            *files,
        ],
        len(files),
        cwd=rules_dir,
    )
    if not stdout.strip():
        return []
    return [_sg_violation(entry) for entry in _sg_entries(stdout)]


def _run_backend(name: str, argv: Sequence[str], file_count: int, **options) -> str:
    """A backend's stdout. Not running at all is a BackendError, never empty
    output: "did not run" must stay distinguishable from "found nothing"."""
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=30, **options
        ).stdout
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            f"{name} timed out after 30s on {file_count} file(s)"
        ) from exc
    except OSError as exc:
        raise BackendError(f"{name} could not be run: {exc}") from exc


def _sg_entries(stdout: str) -> list[dict]:
    """ast-grep emits a JSON array, or NDJSON when streaming."""
    try:
        parsed = json.loads(stdout)
        # If a single JSON object (dict) was parsed instead of an array,
        # wrap it in a list to maintain consistent return type.
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except json.JSONDecodeError:
        pass
    return [_ndjson_entry(line) for line in stdout.strip().splitlines()]


def _ndjson_entry(line: str) -> dict:
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"ast-grep produced unparseable output: {line[:80]!r}"
        ) from exc


def _sg_violation(entry: Mapping) -> LintViolation:
    return LintViolation(
        rule=entry.get("ruleId", "unknown"),
        file=entry.get("file", ""),
        line=entry.get("range", {}).get("start", {}).get("line", 0) + 1,
        message=entry.get("message", ""),
    )


def _validate_ceiling(name: str, value) -> int:
    """A ceiling is a non-negative int -- and `bool` is not one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{name} must be a non-negative integer, got {value!r}")
    return value


def _run_ruff_once(
    ruff_path: str,
    files: Sequence[str],
    select: str,
    max_complexity: int,
    *,
    max_statements: int = _DEFAULT_MAX_STATEMENTS,
    max_positional_args: int = _DEFAULT_MAX_POSITIONAL_ARGS,
) -> list[LintViolation]:
    stdout = _run_backend(
        "ruff",
        [
            ruff_path,
            "check",
            "--output-format",
            "json",
            "--select",
            select,
            "--ignore",
            _DEFAULT_RUFF_IGNORE,
            # An inline --config beats any pyproject.toml the scanned
            # project happens to carry, so the gate's ceiling is the one
            # that applies.
            "--config",
            f"lint.mccabe.max-complexity={max_complexity}",
            "--config",
            f"lint.pylint.max-statements={max_statements}",
            "--config",
            f"lint.pylint.max-positional-args={max_positional_args}",
            *files,
        ],
        len(files),
    )
    return _ruff_violations(stdout)


def _ruff_violations(stdout: str) -> list[LintViolation]:
    if not stdout.strip():
        return []
    try:
        entries = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"ruff produced unparseable output: {stdout[:80]!r}"
        ) from exc

    return [
        LintViolation(
            rule=entry.get("code", "unknown"),
            file=entry.get("filename", ""),
            line=entry.get("location", {}).get("row", 0),
            message=entry.get("message", ""),
        )
        for entry in entries
    ]


def _run_sg(sg_path: str, rules_dir: str, files: Sequence[str]) -> list[LintViolation]:
    # The chunk size is passed explicitly rather than left to the default, so
    # it is read at call time -- a default argument binds once at def time and
    # could not be monkeypatched by a test.
    return [
        violation
        for chunk in _chunked(files, _MAX_PATHS_PER_CALL)
        for violation in _run_sg_once(sg_path, rules_dir, chunk)
    ]


def _run_ruff(
    ruff_path: str,
    files: Sequence[str],
    select: str,
    max_complexity: int,
    *,
    max_statements: int = _DEFAULT_MAX_STATEMENTS,
    max_positional_args: int = _DEFAULT_MAX_POSITIONAL_ARGS,
) -> list[LintViolation]:
    return [
        violation
        for chunk in _chunked(files, _MAX_PATHS_PER_CALL)
        for violation in _run_ruff_once(
            ruff_path,
            chunk,
            select,
            max_complexity,
            max_statements=max_statements,
            max_positional_args=max_positional_args,
        )
    ]
