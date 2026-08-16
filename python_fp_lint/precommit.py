# python_fp_lint/precommit.py
"""Pre-commit gate — lint the staged content, report only newly added lines.

Two things separate this from a plain `check` over the staged filenames:

1. It lints the *staged blob* (`git show :path`), not the worktree file. Those
   differ whenever a file is partially staged, and the commit records the blob.
2. It filters violations to lines added by the staged diff, so an existing
   codebase can adopt the gate without first fixing every pre-existing
   violation. `--all-lines` turns the filter off.
"""

import os
import re
import subprocess

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.result import LintResult, LintViolation

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(repo_root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def staged_python_files(repo_root: str) -> list[str]:
    """Repo-relative paths of staged .py files (added/copied/modified/renamed)."""
    out = _git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in out.split("\0") if p.endswith(".py")]


def _hunk_range(line: str) -> tuple[int, int] | None:
    """Post-image range of one hunk header, or None if not one / pure deletion."""
    match = _HUNK_RE.match(line)
    if match is None:
        return None
    start = int(match.group(1))
    count = 1 if match.group(2) is None else int(match.group(2))
    if count == 0:  # pure deletion — nothing added at this position
        return None
    return start, start + count - 1


def parse_added_ranges(diff_text: str) -> list[tuple[int, int]]:
    """Post-image line ranges added by a unified diff, from its hunk headers."""
    return [
        r
        for r in (_hunk_range(line) for line in diff_text.splitlines())
        if r is not None
    ]


def added_line_ranges(repo_root: str, path: str) -> list[tuple[int, int]]:
    diff = _git(repo_root, "diff", "--cached", "-U0", "--", path)
    return parse_added_ranges(diff)


def _in_any_range(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def filter_to_added_lines(
    violations: list[LintViolation], ranges_by_file: dict[str, list[tuple[int, int]]]
) -> list[LintViolation]:
    """Keep only violations landing on a line the staged diff added."""
    return [
        v for v in violations if _in_any_range(v.line, ranges_by_file.get(v.file, []))
    ]


def materialize_staged(repo_root: str, paths: list[str], dest: str) -> dict[str, str]:
    """Write each staged blob under dest, mirroring its repo-relative path.

    Returns a map of materialized absolute path -> repo-relative path.
    """

    def write_blob(path: str) -> str:
        target = os.path.join(dest, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(_git(repo_root, "show", f":{path}"))
        return os.path.abspath(target)

    return {write_blob(path): path for path in paths}


def _narrow_to_requested(
    staged: list[str], paths: list[str] | None, repo_root: str
) -> list[str]:
    """Intersect the staged set with caller-supplied paths, if any."""
    if paths is None:
        return staged
    wanted = {os.path.relpath(os.path.abspath(p), repo_root) for p in paths}
    return [p for p in staged if p in wanted]


def evaluate_staged(
    repo_root: str,
    workdir: str,
    gate: LintGate,
    paths: list[str] | None = None,
    diff_only: bool = True,
) -> LintResult:
    """Lint staged .py content under repo_root, materializing blobs into workdir.

    `paths` (repo-relative) narrows the staged set — pre-commit passes the
    filenames it selected. `workdir` must be an existing empty directory
    outside the repo; the caller owns its lifetime.
    """
    staged = _narrow_to_requested(staged_python_files(repo_root), paths, repo_root)
    if not staged:
        return LintResult(passed=True, violations=[])

    mapping = materialize_staged(repo_root, staged, workdir)
    result = gate.evaluate(sorted(mapping), repo_root)

    # Rewrite temp paths back to repo-relative ones before filtering/reporting.
    relocated = [
        LintViolation(
            rule=v.rule,
            file=mapping.get(os.path.abspath(v.file), v.file),
            line=v.line,
            message=v.message,
        )
        for v in result.violations
    ]

    violations = (
        filter_to_added_lines(
            relocated, {p: added_line_ranges(repo_root, p) for p in staged}
        )
        if diff_only
        else relocated
    )
    return LintResult(passed=len(violations) == 0, violations=violations)
