# CLAUDE.md

All project rules live in [AGENTS.md](AGENTS.md). Read it first, follow it, and
do not duplicate it here.

Short version:

- `make test` and `make lint` must pass before you report done.
- Layering: router → service → repository → model. No SQL in routers.
- Authz: filter queries by owner, 404 for other users' rows, `AdminUser` for
  admin routes (403 otherwise).
- Refresh tokens: hash at rest, rotate on use, one retry inside the grace
  window, family revoke on any other replay.
- Revocation: logout denylists the access `jti`; role changes bump `not_before`
  (ms precision) so existing tokens die immediately.
- Uploads stream to disk chunk-by-chunk with their own cap; never buffer.
- Redis keys are namespaced and always have a TTL. Celery tasks are thin,
  idempotent wrappers around async functions; exactly one beat process.
- Secrets/config from env only; logs go through `redact()`.
- New resource = copy the `items` slice, plus tests for 401/404/422.
