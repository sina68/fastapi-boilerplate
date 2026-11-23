"""Small operator CLI. No extra dependency: argparse + the app's own session.

    python -m app.cli promote someone@example.com
    docker compose exec api python -m app.cli promote someone@example.com

The first admin cannot come from the API (that would be a privilege-escalation
hole), so promotion happens here, with database access.

Promotion is a role change, so it carries the same invariant as the admin API:
every access token minted before the bump dies on its next request. Otherwise a
stale or stolen token of the promoted user would inherit admin rights.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import denylist
from app.core.config import settings
from app.core.roles import Role
from app.db.redis import close_redis, get_redis_client
from app.db.session import dispose_engine, get_session_maker
from app.repositories import user as user_repo


async def promote(
    email: str,
    *,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
    redis: Redis | None = None,
) -> bool:
    maker = session_maker or get_session_maker()
    async with maker() as session:
        user = await user_repo.get_by_email(session, email.strip().lower())
        if user is None:
            return False
        if user.role == Role.ADMIN.value:
            return True
        user.role = Role.ADMIN.value
        await session.commit()
        user_id = user.id

    owns_redis = redis is None
    client = redis or get_redis_client()
    try:
        await denylist.bump_not_before(
            client,
            user_id=str(user_id),
            access_ttl_seconds=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        )
    finally:
        if owns_redis:
            await close_redis()
    return True


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.command == "promote":
            ok = await promote(args.email)
            if not ok:
                print(f"no user with email {args.email}", file=sys.stderr)
                return 1
            print(f"{args.email} is now {Role.ADMIN.value}")
            return 0
        return 2
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    promote_parser = sub.add_parser("promote", help="grant the admin role to a user")
    promote_parser.add_argument("email")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
