# python_fp_lint/baseline.py
"""The ratchet's baseline file: one whole-repo violation total.

Deliberately just `{"total": N}`. No fingerprint of the ruleset is recorded,
so changing `max_complexity`, `max_statements`, `ruff_select`, `ast_grep_rules`
or a rule file moves the total for reasons unrelated to the code. Re-run
`baseline update` after any such change.
"""

import json
import os


class BaselineError(Exception):
    """The baseline file is missing, unreadable, or holds no valid total."""


def resolve_path(
    cli_value: str | None, config_value: str | None, config_path: str | None
) -> str | None:
    """Baseline file in force: CLI > config file > none (the ratchet is off).

    A relative path in the config file is relative to the config file itself,
    so a config can be checked in beside the baseline it names -- the rule
    lint_rules_dir already follows.
    """
    if cli_value:
        return cli_value
    if not config_value:
        return None
    if config_path:
        base = os.path.dirname(os.path.abspath(config_path))
        return os.path.join(base, config_value)
    return config_value


def read(path: str) -> int:
    """The recorded total, or BaselineError.

    Never falls back to a default. A baseline that cannot be read is not a
    baseline of zero: zero would read as a clean repo and let every commit
    through, which is the opposite of what the file is for.
    """
    if not os.path.exists(path):
        raise BaselineError(
            f"baseline file not found: {path} "
            "-- run `python-fp-lint baseline update` to create it"
        )
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineError(f"cannot read baseline file {path}: {exc}") from exc

    total = data.get("total") if isinstance(data, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise BaselineError(f"baseline file {path} has no valid 'total': {total!r}")
    return total


def write(path: str, total: int) -> None:
    """Record a new total, replacing whatever was there.

    A path that cannot be written -- a directory that does not exist, a
    read-only file -- is a BaselineError like every other baseline failure, so
    it exits 2 with one line rather than a raw OSError traceback.
    """
    try:
        with open(path, "w") as f:
            json.dump({"total": total}, f)
            f.write("\n")
    except OSError as exc:
        raise BaselineError(f"cannot write baseline file {path}: {exc}") from exc
