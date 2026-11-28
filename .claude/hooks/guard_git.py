#!/usr/bin/env python3
# ruff: noqa: S603, S607 - runs fixed git/make argv from PATH on purpose
"""PreToolUse guard for Bash commands run by Claude Code in this repo.

Enforces the workflow rules in AGENTS.md section 1 so they hold even when the
agent forgets them:

- no `--no-verify` / `-n` on commit, no `SKIP=` for pre-commit, no hook removal
- no force push (``--force-with-lease`` allowed on feature branches only)
- no commit, push, merge or tag on protected branches
- no push from a branch without a type prefix (feat/, fix/, ...)
- no push unless `make lint` and `make test` pass

Exit code 2 blocks the tool call; stderr is shown to the agent.
Standard library only, so it runs before `make install`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROTECTED = {"dev", "stage", "main", "master", "prod"}
BRANCH_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")


def block(reason: str) -> None:
    print(f"BLOCKED by .claude/hooks/guard_git.py: {reason}", file=sys.stderr)
    sys.exit(2)


def project_dir(payload: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")


def current_branch(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def git_args(segment: str) -> tuple[list[str], list[str]] | None:
    """Return (env_assignments, args_after_git) if the segment runs git."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    env: list[str] = []
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        env.append(tokens.pop(0))
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    args = tokens[1:]
    # drop global options like `-C path` / `-c key=val`
    while args and args[0] in {"-C", "-c"} and len(args) > 1:
        if args[0] == "-c" and "core.hookspath" in args[1].lower():
            block("overriding core.hooksPath is not allowed.")
        args = args[2:]
    return env, args


def run_checks(cwd: Path) -> None:
    for target in ("lint", "test"):
        result = subprocess.run(
            ["make", target],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-30:])
            block(f"`make {target}` failed; fix it before pushing.\n{tail}")


def check_segment(segment: str, cwd: Path) -> bool:
    """Validate one shell segment. Returns True if it is a `git push`."""
    parsed = git_args(segment)
    if parsed is None:
        if re.search(r"\bpre-commit\s+uninstall\b", segment):
            block("uninstalling git hooks is not allowed.")
        return False
    env, args = parsed
    if not args:
        return False
    sub, rest = args[0], args[1:]

    if any(e.startswith(("SKIP=", "PRE_COMMIT_ALLOW_NO_CONFIG=")) for e in env):
        block("skipping pre-commit hooks is not allowed.")
    if "--no-verify" in rest:
        block("--no-verify is not allowed; fix what the hook reports.")
    if sub == "config" and any("hookspath" in a.lower() for a in rest):
        block("changing core.hooksPath is not allowed.")

    branch = current_branch(cwd)

    if sub == "commit":
        short_flags = [a for a in rest if re.fullmatch(r"-[a-zA-Z]+", a)]
        if any("n" in a for a in short_flags):
            block("`git commit -n` skips hooks; not allowed.")
        if branch in PROTECTED:
            block(
                f"you are on protected branch `{branch}`. Create a feature branch from dev first."
            )

    if sub in {"merge", "rebase", "cherry-pick"} and branch in PROTECTED:
        block(f"`git {sub}` on protected branch `{branch}` is not allowed; use an MR.")

    if sub == "tag" and rest and not set(rest) & {"-l", "--list", "-n"}:
        block("creating or deleting tags is a release step for humans only.")

    if sub == "push":
        if branch and branch not in PROTECTED and branch != "HEAD":
            if not any(branch.startswith(t + "/") for t in BRANCH_TYPES):
                block(
                    f"branch `{branch}` must start with a type prefix "
                    f"({', '.join(t + '/' for t in BRANCH_TYPES)}). Rename it with "
                    "`git branch -m <type>/<name>` and push again."
                )
        if any(a in {"--force", "-f", "--mirror", "--delete", "-d"} for a in rest):
            block("force/mirror/delete push is not allowed.")
        if any(a.startswith("+") for a in rest):
            block("force refspec (+ref) is not allowed.")
        # str.removeprefix needs 3.9; keep this runnable on an old system python3.
        targets = {
            re.sub(r"^refs/heads/", "", a.split(":")[-1]) for a in rest if not a.startswith("-")
        }
        if branch in PROTECTED or targets & PROTECTED:
            block(
                f"pushing to a protected branch ({', '.join(sorted(PROTECTED))}) "
                "is not allowed; open an MR."
            )
        if "--force-with-lease" in " ".join(rest) and branch in PROTECTED:
            block("force-with-lease on a protected branch is not allowed.")
        return True
    return False


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = project_dir(payload)
    is_push = False
    for segment in SEGMENT_SPLIT.split(command):
        if segment.strip():
            is_push = check_segment(segment.strip(), cwd) or is_push
    if is_push:
        run_checks(cwd)
    sys.exit(0)


if __name__ == "__main__":
    main()
