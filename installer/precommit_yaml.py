#!/usr/bin/env python3
"""Add or remove a `- repo:` block in a project's .pre-commit-config.yaml.

Shared by the install/uninstall scripts for each tool this repo wires up.

Every edit is textual, line by line, rather than a YAML round-trip. A
round-trip would drop the consumer's comments and reorder their keys, and
that file belongs to them, not to us.

Usage:
    precommit_yaml.py insert --config PATH --url URL --rev REV --hooks JSON
    precommit_yaml.py remove --config PATH --url URL

`--hooks` is a JSON list of objects: `{"id": ..., "args": [...]}`, where
`args` is optional. `insert` is idempotent, and reconciles rather than
replaces: a block that is already present gains any hook ids it is missing
and keeps everything else about it untouched.
"""

import argparse
import json
import os
import re
import sys

_ID = re.compile(r"^(\s*)-\s+id:\s*([\w.-]+)")


def repo_item(url: str) -> re.Pattern:
    """Matches the `- repo: <url>` line, with or without quotes or a `.git`."""
    return re.compile(
        rf"^(\s*)-\s+repo:\s*['\"]?{re.escape(url)}(\.git)?['\"]?\s*(#.*)?$"
    )


def hook_lines(pad: str, hook: dict) -> list[str]:
    lines = [f"{pad}- id: {hook['id']}\n"]
    for key in ("args", "stages"):
        if hook.get(key):
            lines.append(f"{pad}  {key}: [{', '.join(hook[key])}]\n")
    return lines


def block_lines(indent: int, url: str, rev: str, hooks: list[dict]) -> list[str]:
    pad = " " * indent
    return [
        f"{pad}- repo: {url}\n",
        f"{pad}  rev: {rev}\n",
        f"{pad}  hooks:\n",
        *[line for hook in hooks for line in hook_lines(pad + "    ", hook)],
    ]


def find_block(lines: list[str], url: str) -> tuple[int, int] | None:
    """(index, indent) of the repo item for `url`, or None when absent."""
    item = repo_item(url)
    found = next(((i, m) for i, m in enumerate(map(item.match, lines)) if m), None)
    return None if found is None else (found[0], len(found[1].group(1)))


def block_end(lines: list[str], start: int, indent: int) -> int:
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


def content_end(lines: list[str], start: int, indent: int) -> int:
    """Index one past the block's last non-blank line -- where to append to it.

    The mirror of block_end: appending has to stay *above* the trailing blanks
    that removal consumes, or a new hook lands after the separator and outside
    the block it belongs to.
    """
    end = block_end(lines, start, indent)
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def add_missing_hooks(
    lines: list[str], start: int, indent: int, hooks: list[dict]
) -> tuple[list[str], list[str]]:
    """Append whatever hook ids the existing block lacks, in the given order."""
    end = content_end(lines, start, indent)
    present = {m.group(2) for m in map(_ID.match, lines[start:end]) if m}
    missing = [hook for hook in hooks if hook["id"] not in present]
    if not missing:
        return lines, []
    pads = [m.group(1) for m in map(_ID.match, lines[start:end]) if m]
    pad = pads[0] if pads else " " * (indent + 4)
    added = [line for hook in missing for line in hook_lines(pad, hook)]
    return [*lines[:end], *added, *lines[end:]], [hook["id"] for hook in missing]


def list_indent(lines: list[str], repos_at: int) -> int:
    """The indent the file already uses for its repo items; 2 when it has none."""
    item = next(
        (m for m in (re.match(r"^(\s*)-\s", x) for x in lines[repos_at + 1 :]) if m),
        None,
    )
    return len(item.group(1)) if item else 2


def insert(path: str, url: str, rev: str, hooks: list[dict]) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = None

    if lines is None:
        out = ["repos:\n", *block_lines(2, url, rev, hooks)]
    else:
        at = find_block(lines, url)
        if at is not None:
            out, added = add_missing_hooks(lines, at[0], at[1], hooks)
            if not added:
                print("  already wired, skipping.")
                return
            print(f"  already wired, adding: {', '.join(added)}.")
        else:
            repos_at = next(
                (i for i, x in enumerate(lines) if re.match(r"^repos:\s*$", x)), None
            )
            if repos_at is None:
                # No repos: key -- append one rather than guessing where it belongs.
                tail = "" if not lines or lines[-1].endswith("\n") else "\n"
                out = [*lines, f"{tail}repos:\n", *block_lines(2, url, rev, hooks)]
            else:
                # Insert at the head of the list so the block cannot attach
                # itself to a later top-level key, at the file's own indent.
                indent = list_indent(lines, repos_at)
                out = [
                    *lines[: repos_at + 1],
                    *block_lines(indent, url, rev, hooks),
                    *lines[repos_at + 1 :],
                ]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"  wrote {path}")


def remove(path: str, url: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("  no .pre-commit-config.yaml, skipping.")
        return

    at = find_block(lines, url)
    if at is None:
        print("  not wired, skipping.")
        return

    start, indent = at
    out = [*lines[:start], *lines[block_end(lines, start, indent) :]]

    if any(re.match(r"^\s*-\s+repo:", x) for x in out):
        pass
    elif all(
        not x.strip() or x.lstrip().startswith("#") or re.match(r"^repos:\s*$", x)
        for x in out
    ):
        # Nothing left but an empty `repos:` -- the installer created this file.
        os.remove(path)
        print(f"  removed {path}")
        return
    else:
        # A bare `repos:` is null, which pre-commit rejects; keep it a list.
        out = ["repos: []\n" if re.match(r"^repos:\s*$", x) else x for x in out]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"  wrote {path}")


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
