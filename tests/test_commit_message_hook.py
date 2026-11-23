"""The commit-msg hook is the repo standard; keep its rules tested."""

from __future__ import annotations

import pytest
from conventional_commits_check import is_valid


@pytest.mark.parametrize(
    "message",
    [
        "feat(auth): add refresh rotation",
        "fix: handle replay grace window",
        "chore(deps): bump redis",
        "✨ add refresh rotation",
        "📝 docs: explain revocation",
        "Merge branch 'dev' into 'main'",
        'Revert "feat: something"',
    ],
)
def test_accepts_conventional_and_gitmoji_messages(message: str) -> None:
    assert is_valid(message)


@pytest.mark.parametrize(
    "message",
    [
        "",
        "fixed stuff",
        "wip",
        "auth changes: rotation",
        "feat:",
    ],
)
def test_rejects_other_messages(message: str) -> None:
    assert not is_valid(message)
