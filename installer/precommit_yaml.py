#!/usr/bin/env python3
"""Add or remove a `- repo:` block in a project's .pre-commit-config.yaml.

Shared by the install/uninstall scripts for each tool this repo wires up.

Every edit is textual, line by line, rather than a YAML round-trip. A
round-trip would drop the consumer's comments and reorder their keys, and
that file belongs to them, not to us.

Usage:
    precommit_yaml.py insert --config PATH --url URL --rev REV --hooks JSON
    precommit_yaml.py remove --config PATH --url URL

`--hooks` is a JSON list of objects: `{"id": ..., "args": [...], "stages":
[...]}`, where `args` and `stages` are optional. `insert` is idempotent, and
reconciles rather than replaces: a block that is already present gains any
hook ids it is missing, and any of those keys we declare that a present hook
lacks. A key the consumer already wrote is never overwritten.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence


def _emit(text: str) -> None:
    """One line of installer progress. Run by the system python3 from the shell
    installers, outside the package, so it cannot use python_fp_lint.output."""
    sys.stdout.write(text + "\n")


_ID = re.compile(r"^(\s*)-\s+id:\s*([\w.-]+)")


def repo_item(url: str) -> re.Pattern:
    """Matches the `- repo: <url>` line, with or without quotes or a `.git`."""
    return re.compile(
        rf"^(\s*)-\s+repo:\s*['\"]?{re.escape(url)}(\.git)?['\"]?\s*(#.*)?$"
    )


def hook_lines(pad: str, hook: Mapping) -> list[str]:
    return [
        f"{pad}- id: {hook['id']}\n",
        *(
            f"{pad}  {key}: [{', '.join(hook[key])}]\n"
            for key in ("args", "stages")
            if hook.get(key)
        ),
    ]


def block_lines(indent: int, url: str, rev: str, hooks: Sequence[dict]) -> list[str]:
    pad = " " * indent
    return [
        f"{pad}- repo: {url}\n",
        f"{pad}  rev: {rev}\n",
        f"{pad}  hooks:\n",
        *[line for hook in hooks for line in hook_lines(pad + "    ", hook)],
    ]


def find_block(lines: Sequence[str], url: str) -> tuple[int, int] | None:
    """(index, indent) of the repo item for `url`, or None when absent."""
    item = repo_item(url)
    found = next(((i, m) for i, m in enumerate(map(item.match, lines)) if m), None)
    return None if found is None else (found[0], len(found[1].group(1)))


def block_end(lines: Sequence[str], start: int, indent: int) -> int:
    """Index one past the block, trailing blank lines included.

    The block runs to the first non-blank line at or left of its own dash.
    Blank lines after it separate it from what follows, so they count as part
    of it: removing the block takes them along rather than leaving a doubled
    separator behind.
    """
    return next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent
        ),
        len(lines),
    )


def content_end(lines: Sequence[str], start: int, indent: int) -> int:
    """Index one past the block's last non-blank line -- where to append to it.

    The mirror of block_end: appending has to stay *above* the trailing blanks
    that removal consumes, or a new hook lands after the separator and outside
    the block it belongs to.
    """
    end = block_end(lines, start, indent)
    # Walk back over trailing blanks, never past the block's first line.
    return next(
        (i for i in range(end, start + 1, -1) if lines[i - 1].strip()), start + 1
    )


def hook_span(lines: Sequence[str], id_at: int, pad: str) -> int:
    """Index one past the hook item whose `- id:` line is at `id_at`.

    A hook's own fields are indented deeper than its dash, so the first non-blank
    line at or left of the dash belongs to the next hook -- or to whatever
    follows the list.
    """
    return next(
        (
            i
            for i in range(id_at + 1, len(lines))
            if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= len(pad)
        ),
        len(lines),
    )


def absent_fields(
    lines: Sequence[str], id_at: int, hook: Mapping
) -> list[tuple[str, str]]:
    """(field, line) for each field we declare that this hook does not already have.

    Each line goes directly under the `- id:` line rather than at the end of the
    hook, so a trailing comment stays attached to the field it was written for.
    """
    pad = _ID.match(lines[id_at]).group(1)
    body = lines[id_at + 1 : hook_span(lines, id_at, pad)]
    return [
        (field, f"{pad}  {field}: [{', '.join(hook[field])}]\n")
        for field in ("args", "stages")
        if hook.get(field)
        and not any(re.match(rf"^\s*{field}:", line) for line in body)
    ]


def backfill_fields(
    lines: Sequence[str], start: int, indent: int, hooks: Sequence[dict]
) -> tuple[list[str], list[str]]:
    """Add fields we declare to a hook that is already present but lacks them.

    Absent fields only. A `stages:` or `args:` the consumer wrote is theirs, and
    reconciling an existing block is not licence to overwrite it. Without this,
    a fix to what we declare -- `stages: [pre-commit]`, say -- would only ever
    reach repos wired from scratch, while every existing consumer kept the old
    wiring and was told "already wired, skipping".
    """
    wanted = {hook["id"]: hook for hook in hooks}
    # Our own block only: the consumer's other hooks are their business.
    ids = {
        i: match.group(2)
        for i, match in (
            (j, _ID.match(lines[j]))
            for j in range(start, content_end(lines, start, indent))
        )
        if match is not None and match.group(2) in wanted
    }
    extra = {i: absent_fields(lines, i, wanted[hook_id]) for i, hook_id in ids.items()}
    return (
        [
            emitted
            for i, line in enumerate(lines)
            for emitted in (line, *(added for _, added in extra.get(i, ())))
        ],
        [f"{ids[i]} {field}" for i, fields in extra.items() for field, _ in fields],
    )


def add_missing_hooks(
    lines: Sequence[str], start: int, indent: int, hooks: Sequence[dict]
) -> tuple[list[str], list[str]]:
    """Append whatever hook ids the existing block lacks, in the given order.

    Hooks that are already there keep their place, and gain only the fields we
    declare and they lack -- see backfill_fields.
    """
    reconciled, backfilled = backfill_fields(lines, start, indent, hooks)
    end = content_end(reconciled, start, indent)
    present = {m.group(2) for m in map(_ID.match, reconciled[start:end]) if m}
    missing = [hook for hook in hooks if hook["id"] not in present]
    if not missing:
        return reconciled, backfilled
    pads = [m.group(1) for m in map(_ID.match, reconciled[start:end]) if m]
    pad = pads[0] if pads else " " * (indent + 4)
    added = [line for hook in missing for line in hook_lines(pad, hook)]
    return [*reconciled[:end], *added, *reconciled[end:]], [
        *backfilled,
        *(hook["id"] for hook in missing),
    ]


def list_indent(lines: Sequence[str], repos_at: int) -> int:
    """The indent the file already uses for its repo items; 2 when it has none."""
    item = next(
        (m for m in (re.match(r"^(\s*)-\s", x) for x in lines[repos_at + 1 :]) if m),
        None,
    )
    return len(item.group(1)) if item else 2


def _read_lines(path: str) -> list[str]:
    """The file's lines. A missing file reads as no lines, which inserts
    exactly as a new file would: a fresh `repos:` and the block."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        return []


def _write(path: str, lines: Sequence[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    _emit(f"  wrote {path}")


def _with_new_block(
    lines: Sequence[str], url: str, rev: str, hooks: Sequence[dict]
) -> list[str]:
    """`lines` with a whole new repo block for `url` added."""
    repos_at = next(
        (i for i, x in enumerate(lines) if re.match(r"^repos:\s*$", x)), None
    )
    if repos_at is None:
        # No repos: key -- append one rather than guessing where it belongs.
        tail = "" if not lines or lines[-1].endswith("\n") else "\n"
        return [*lines, f"{tail}repos:\n", *block_lines(2, url, rev, hooks)]
    # Insert at the head of the list so the block cannot attach itself to a
    # later top-level key, at the file's own indent.
    indent = list_indent(lines, repos_at)
    return [
        *lines[: repos_at + 1],
        *block_lines(indent, url, rev, hooks),
        *lines[repos_at + 1 :],
    ]


def insert(path: str, url: str, rev: str, hooks: Sequence[dict]) -> None:
    lines = _read_lines(path)
    at = find_block(lines, url)
    if at is None:
        _write(path, _with_new_block(lines, url, rev, hooks))
        return
    out, added = add_missing_hooks(lines, at[0], at[1], hooks)
    if not added:
        _emit("  already wired, skipping.")
        return
    _emit(f"  already wired, adding: {', '.join(added)}.")
    _write(path, out)


def remove(path: str, url: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        _emit("  no .pre-commit-config.yaml, skipping.")
        return

    at = find_block(lines, url)
    if at is None:
        _emit("  not wired, skipping.")
        return

    start, indent = at
    kept = [*lines[:start], *lines[block_end(lines, start, indent) :]]

    if any(re.match(r"^\s*-\s+repo:", x) for x in kept):
        _write(path, kept)
        return
    if all(
        not x.strip() or x.lstrip().startswith("#") or re.match(r"^repos:\s*$", x)
        for x in kept
    ):
        # Nothing left but an empty `repos:` -- the installer created this file.
        os.remove(path)
        _emit(f"  removed {path}")
        return
    # A bare `repos:` is null, which pre-commit rejects; keep it a list.
    _write(path, ["repos: []\n" if re.match(r"^repos:\s*$", x) else x for x in kept])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--config", required=True, metavar="PATH")
        p.add_argument("--url", required=True)
        return p

    add = common(sub.add_parser("insert"))
    add.add_argument("--rev", required=True)
    add.add_argument("--hooks", required=True, metavar="JSON")

    common(sub.add_parser("remove"))

    args = parser.parse_args()
    if args.command == "insert":
        insert(args.config, args.url, args.rev, json.loads(args.hooks))
    else:
        remove(args.config, args.url)


if __name__ == "__main__":
    sys.exit(main())
