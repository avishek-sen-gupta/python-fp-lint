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
from functools import cache

from python_fp_lint.reassignment_gate import ReassignmentGate
from python_fp_lint.result import LintResult, LintViolation

# Ruff rule selection — batteries-included + FP-specific
_DEFAULT_RUFF_SELECT = "E,F,W,I,B,UP,SIM,RUF,BLE,T20,TID252,C901,PLR0915,ANN401"
_DEFAULT_RUFF_IGNORE = "E501,W292"
# Ruff's C901 ceiling. Deliberately stricter than Ruff's own default of 10:
# a function past three branches is asking to be decomposed.
_DEFAULT_MAX_COMPLEXITY = 3
# Ruff's PLR0915 ceiling, counted in statements rather than physical lines.
# Deliberately stricter than Ruff's own default of 50.
_DEFAULT_MAX_STATEMENTS = 10


class LintGate:
    """Unified lint gate — runs ast-grep, Ruff, and beniget reassignment detection."""

    def __init__(
        self,
        rules_dir: str | None = None,
        ruff_select: str | None = None,
        ast_grep_rules: list[str] | None = None,
        rules_cache_root: str | None = None,
        config_path: str | None = None,
        exclude: list[str] | None = None,
        max_complexity: int | None = None,
        max_statements: int | None = None,
    ):
        self.rules_dir = rules_dir
        self.ruff_select = ruff_select
        self.ast_grep_rules = ast_grep_rules
        self.rules_cache_root = rules_cache_root
        self.config_path = config_path
        self.exclude = exclude
        self.max_complexity = max_complexity
        self.max_statements = max_statements

    def _config(self, key):
        return _read_config(key, self.config_path)

    def evaluate(self, changed_files: list[str], project_root: str) -> LintResult:
        py_files = self.filter_excluded(
            _filter_python_files(changed_files), project_root
        )
        if not py_files:
            return LintResult(passed=True, violations=[])

        violations = []
        violations.extend(self._run_ast_grep(py_files, project_root))
        violations.extend(self._run_ruff(py_files))
        violations.extend(self._run_reassignment(py_files, project_root))

        return LintResult(passed=len(violations) == 0, violations=violations)

    def resolve_exclude(self) -> list[str]:
        """Exclude globs in force: constructor > config file > nothing."""
        if self.exclude is not None:
            return self.exclude
        config_val = self._config("exclude")
        if config_val and isinstance(config_val, list):
            return config_val
        return []

    def is_excluded(self, path: str, project_root: str) -> bool:
        """True when path matches one of the configured exclude globs."""
        return is_excluded(path, project_root, self.resolve_exclude())

    def filter_excluded(self, files: list[str], project_root: str) -> list[str]:
        """Drop every path matching an exclude glob."""
        patterns = self.resolve_exclude()
        if not patterns:
            return files
        return [f for f in files if not is_excluded(f, project_root, patterns)]

    def _resolve_ast_grep_rules(self) -> list[str] | None:
        if self.ast_grep_rules is not None:
            return self.ast_grep_rules
        config_val = self._config("ast_grep_rules")
        if config_val and isinstance(config_val, list):
            return config_val
        return None

    def _run_ast_grep(self, files: list[str], project_root: str) -> list[LintViolation]:
        rules_dir = self._resolve_rules_dir(project_root)
        if rules_dir is None:
            return []

        sg = _find_sg()
        if sg is None:
            return []

        sgconfig = os.path.join(rules_dir, "sgconfig.yml")
        if not os.path.exists(sgconfig):
            return []

        # The package copy normally lives in the consumer's .venv, which is
        # gitignored -- and ast-grep silently matches nothing under an ignored
        # path -- so it has to be copied out before scanning. A rules dir the
        # consumer pointed us at is used where it stands.
        scan_dir = (
            _materialize_rules_dir(rules_dir, self.rules_cache_root)
            if os.path.abspath(rules_dir) == _package_rules_dir()
            else rules_dir
        )
        violations = _run_sg(sg, scan_dir, files)
        allowed = self._resolve_ast_grep_rules()
        if allowed is not None:
            violations = [v for v in violations if v.rule in allowed]
        return violations

    def _resolve_ruff_select(self) -> str:
        if self.ruff_select:
            return self.ruff_select
        config_select = self._config("ruff_select")
        if config_select:
            return config_select
        return _DEFAULT_RUFF_SELECT

    def _resolve_max_complexity(self) -> int:
        """Complexity ceiling in force: constructor > config file > default."""
        if self.max_complexity is not None:
            return _validate_max_complexity(self.max_complexity)
        config_val = self._config("max_complexity")
        if config_val is None:
            return _DEFAULT_MAX_COMPLEXITY
        return _validate_max_complexity(config_val)

    def _resolve_max_statements(self) -> int:
        """Statement ceiling in force: constructor > config file > default."""
        if self.max_statements is not None:
            return _validate_ceiling("max_statements", self.max_statements)
        config_val = self._config("max_statements")
        if config_val is None:
            return _DEFAULT_MAX_STATEMENTS
        return _validate_ceiling("max_statements", config_val)

    def _run_ruff(self, files: list[str]) -> list[LintViolation]:
        ruff = _find_ruff()
        if ruff is None:
            return []
        return _run_ruff(
            ruff,
            files,
            self._resolve_ruff_select(),
            self._resolve_max_complexity(),
            max_statements=self._resolve_max_statements(),
        )

    def _run_reassignment(
        self, files: list[str], project_root: str
    ) -> list[LintViolation]:
        result = ReassignmentGate().evaluate(files, project_root)
        return result.violations

    def _resolve_rules_dir(self, project_root: str) -> str | None:
        configured = self._config("lint_rules_dir")
        if configured and self.config_path:
            # A relative lint_rules_dir is relative to the config file itself,
            # so a config can be checked in beside the rules it points at.
            base = os.path.dirname(os.path.abspath(self.config_path))
            configured = os.path.join(base, configured)
        return _resolve_rules_dir(self.rules_dir, project_root, configured)


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


def _expand_paths(paths: list[str]) -> list[str]:
    """Expand directories, globs, and plain files into a flat list of paths."""
    expanded = []
    for p in paths:
        if os.path.isdir(p):
            expanded.extend(_walk_directory(p))
        elif any(c in p for c in ("*", "?", "[")):
            expanded.extend(glob.glob(p, recursive=True))
        else:
            expanded.append(p)
    return expanded


def _filter_python_files(files: list[str]) -> list[str]:
    """Expand dirs/globs, then filter to existing, unique .py files."""
    seen = set()
    result = []
    for f in _expand_paths(files):
        real = os.path.abspath(f)
        if real in seen:
            continue
        seen.add(real)
        if real.endswith(".py") and os.path.exists(real):
            result.append(real)
    return result


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


def is_excluded(path: str, project_root: str, patterns: list[str]) -> bool:
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


def _package_rules_dir() -> str:
    """The rules shipped inside the installed package."""
    return os.path.dirname(os.path.abspath(__file__))


def _default_rules_cache_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".cache", "python_fp_lint", "rules")


def _rules_signature(rules_dir: str) -> str:
    """Content hash of every file under rules_dir, used as its cache key."""
    digest = hashlib.sha256()
    for root, _dirs, files in sorted(os.walk(rules_dir)):
        for name in sorted(files):
            path = os.path.join(root, name)
            digest.update(os.path.relpath(path, rules_dir).encode())
            with open(path, "rb") as f:
                digest.update(f.read())
    return digest.hexdigest()


def _materialize_rules_dir(source_dir: str, cache_root: str | None) -> str:
    """Copy rules_dir to a stable location outside any consumer's git tree.

    ast-grep silently finds zero matches for rule files that live under a
    path excluded by the enclosing git repo's .gitignore -- e.g. a project's
    own .venv, where this package is normally installed -- regardless of
    --no-ignore flags. Scanning always uses a copy under the cache root
    instead, which is never inside a consumer's tree.
    """
    root = cache_root or _default_rules_cache_root()
    target = os.path.join(root, _rules_signature(source_dir))
    if not os.path.isdir(target):
        tmp_target = target + ".tmp"
        if os.path.isdir(tmp_target):
            shutil.rmtree(tmp_target)
        os.makedirs(root, exist_ok=True)
        shutil.copytree(source_dir, tmp_target)
        os.replace(tmp_target, target)
    return target


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


def _resolve_rules_dir(
    explicit_dir: str | None, project_root: str, config_dir: str | None = None
) -> str | None:
    """Find the lint rules directory.

    Searches in order: explicit rules_dir, lint_rules_dir from the config file,
    project-local scripts/lint/, then package-local (next to this file).

    The config file outranks the package copy deliberately: the package copy
    always exists, so anything below it in the order could never win.
    """
    if explicit_dir:
        return explicit_dir
    candidates = ([config_dir] if config_dir else []) + [
        os.path.join(project_root, "scripts", "lint"),
        _package_rules_dir(),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate) and os.path.exists(
            os.path.join(candidate, "sgconfig.yml")
        ):
            return candidate
    return None


class ConfigError(Exception):
    """An explicitly-specified config file is missing or unreadable."""


class BackendError(Exception):
    """A lint backend could not be run, so its findings are unknown.

    Deliberately not an empty result: "the linter did not run" and "the code
    is clean" must stay distinguishable. The ratchet treats zero violations
    as an improvement and tightens the baseline, so a silent failure would
    write a baseline of zero and destroy the recorded debt.
    """


def _read_config(key: str, config_path: str | None = None):
    """Read one key from an explicitly named config file.

    There is no search and no default location: config_path is either given,
    or there is no config and built-in defaults apply. A named file that is
    missing or malformed raises ConfigError rather than silently falling back
    to defaults the caller did not ask for.
    """
    if config_path is None:
        return None
    if not os.path.exists(config_path):
        raise ConfigError(f"config file not found: {config_path}")
    try:
        with open(config_path) as f:
            return json.load(f).get(key)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read config file {config_path}: {exc}") from exc


def _run_sg(sg_path: str, rules_dir: str, files: list[str]) -> list[LintViolation]:
    try:
        result = subprocess.run(
            [
                sg_path,
                "scan",
                "--json",
                "--config",
                os.path.join(rules_dir, "sgconfig.yml"),
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=rules_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            f"ast-grep timed out after 30s on {len(files)} file(s)"
        ) from exc
    except OSError as exc:
        raise BackendError(f"ast-grep could not be run: {exc}") from exc

    if not result.stdout.strip():
        return []
    return [_sg_violation(entry) for entry in _sg_entries(result.stdout)]


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
    entries = []
    for line in stdout.strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"ast-grep produced unparseable output: {line[:80]!r}"
            ) from exc
    return entries


def _sg_violation(entry: dict) -> LintViolation:
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


def _validate_max_complexity(value) -> int:
    return _validate_ceiling("max_complexity", value)


def _run_ruff(
    ruff_path: str,
    files: list[str],
    select: str,
    max_complexity: int,
    max_statements: int = _DEFAULT_MAX_STATEMENTS,
) -> list[LintViolation]:
    try:
        result = subprocess.run(
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
            ]
            + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"ruff timed out after 30s on {len(files)} file(s)") from exc
    except OSError as exc:
        raise BackendError(f"ruff could not be run: {exc}") from exc

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"ruff produced unparseable output: {result.stdout[:80]!r}"
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
