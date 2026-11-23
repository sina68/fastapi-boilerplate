#!/usr/bin/env python3
"""Reject commit messages that are neither Conventional Commits nor gitmoji.

Same rule as the service repos: `type(scope)?: subject` or an emoji prefix.

    feat(auth): add refresh rotation
    ✨ add refresh rotation
"""

from __future__ import annotations

import re
import sys

CONVENTIONAL = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([a-z0-9._-]+\))?!?: .+",
    re.IGNORECASE,
)
GITMOJI = re.compile(r"^[^\w\s]{1,4}\s*\S", re.UNICODE)
MERGE = re.compile(r"^(Merge|Revert) ")


def is_valid(message: str) -> bool:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if not first_line:
        return False
    return bool(
        CONVENTIONAL.match(first_line) or GITMOJI.match(first_line) or MERGE.match(first_line)
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: conventional_commits_check.py <commit-msg-file>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        message = handle.read()
    if is_valid(message):
        return 0
    print(
        "commit message rejected.\n"
        "Use Conventional Commits, e.g. `feat(auth): add refresh rotation`,\n"
        "or a gitmoji prefix, e.g. `✨ add refresh rotation`.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
