# python_fp_lint/precommit.py
"""Pre-commit gate — lint the staged content of every staged Python file.

What separates this from a plain `check` over the staged filenames is that it
lints the *staged blob* (`git show :path`), not the worktree file. Those differ
whenever a file is partially staged, and the commit records the blob.

Every violation in a staged file blocks the commit, including ones that predate
the change being committed.
"""

import os
import subprocess

from python_fp_lint.lint_gate import LintGate
from python_fp_lint.result import LintResult, LintViolation


def git_bytes(repo_root: str, *args: str) -> bytes:
    """Run git in repo_root and return raw stdout, raising on a non-zero exit.

    Bytes rather than text because the callers include `git show :path`, whose
    stdout is a tracked blob. A repo is entitled to hold a latin-1 (or any
    other non-UTF-8) source file, and decoding one here would abort the whole
    run inside subprocess with a UnicodeDecodeError rather than lint it.
    """
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        cwd=repo_root,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout


def git_output(repo_root: str, *args: str) -> str:
    """`git_bytes` decoded for the commands whose stdout is a path list.

    `surrogateescape` so that a path git cannot round-trip through UTF-8 still
    survives as a usable str rather than raising.
    """
    return git_bytes(repo_root, *args).decode("utf-8", errors="surrogateescape")


def staged_python_files(repo_root: str) -> list[str]:
    """Repo-relative paths of staged .py files (added/copied/modified/renamed)."""
    out = git_output(
        repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
    )
    return [p for p in out.split("\0") if p.endswith(".py")]


def materialize_staged(repo_root: str, paths: list[str], dest: str) -> dict[str, str]:
    """Write each staged blob under dest, mirroring its repo-relative path.

    Returns a map of materialized absolute path -> repo-relative path.

    Bytes in, bytes out: the blob is copied verbatim, so a non-UTF-8 source
    file is linted rather than crashing the gate on the way to the temp tree.
    """

    def write_blob(path: str) -> str:
        target = os.path.join(dest, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(git_bytes(repo_root, "show", f":{path}"))
        return os.path.abspath(target)

    return {write_blob(path): path for path in paths}


def remap_to_repo_relative(result: LintResult, mapping: dict[str, str]) -> LintResult:
    """Re-label violations with repo-relative paths rather than scanned ones.

    `mapping` is materialized-absolute-path -> repo-relative path, as
    `materialize_staged` returns it. Violations are reported at the
    repo-relative path rather than the temp one that was actually scanned.
    """
    violations = [
        LintViolation(
            rule=v.rule,
            file=mapping.get(os.path.abspath(v.file), v.file),
            line=v.line,
            message=v.message,
        )
        for v in result.violations
    ]
    return LintResult(passed=len(violations) == 0, violations=violations)


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
) -> LintResult:
    """Lint staged .py content under repo_root, materializing blobs into workdir.

    `paths` (repo-relative) narrows the staged set — pre-commit passes the
    filenames it selected. `workdir` must be an existing empty directory
    outside the repo; the caller owns its lifetime.
    """
    # Exclusions are applied to the repo-relative names, before blobs are
    # materialized: once written under workdir a file no longer sits at a
    # path the project's globs describe.
    staged = gate.filter_excluded(
        _narrow_to_requested(staged_python_files(repo_root), paths, repo_root),
        repo_root,
    )
    if not staged:
        return LintResult(passed=True, violations=[])

    mapping = materialize_staged(repo_root, staged, workdir)
    result = gate.evaluate(sorted(mapping), repo_root)
    return remap_to_repo_relative(result, mapping)
