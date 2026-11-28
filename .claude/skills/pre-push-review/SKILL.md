---
name: pre-push-review
description: Self-review the current branch against AGENTS.md before pushing or opening an MR — runs lint/tests, checks the diff against the team checklist, and drafts the MR description from the GitLab template. Use before every push, when asked to "review my changes", or before creating an MR.
---

# Pre-push review

You are reviewing your own branch the way the human reviewer will. Be strict;
the reviewer will reject anything this misses.

## Steps

1. **Context**
   - `git fetch origin dev` (if it fails, review against local `dev`).
   - `git rev-parse --abbrev-ref HEAD` — must not be a protected branch and must
     start with a type prefix (`feat/`, `fix/`, `refactor/`, `docs/`, `chore/`, ...).
   - `git log --format='%s' origin/dev..HEAD` — every subject must be
     `type(scope): subject` (an optional emoji prefix is fine).
   - `git diff --stat origin/dev...HEAD` and then the full diff.

2. **Gates** — run and record the result:
   ```bash
   make lint
   make test
   ```
   If models changed and Postgres is available: `make migration-check`.
   If `deploy/helm/**` changed: `helm lint` + `helm template` for each values file.
   Any failure = stop, fix, restart the review.

3. **Checklist** — go through AGENTS.md section 7 item by item, plus the rule
   file in `.claude/rules/` for every path area the diff touches. For each item
   decide ✅ / ❌ / n/a and, for ❌, cite `file:line`.

   Look specifically for:
   - SQL or session use outside repositories; business logic in routers.
   - New code under `src/app/` (old layout).
   - Missing tests for new behaviour; missing 401/404/422 (403 for admin) tests.
   - Env vars not added to `Settings` + `.env.example` + `tests/conftest.py` +
     Helm values.
   - Migrations missing, irreversible, or creating a second head.
   - Outbound HTTP without timeout/adapter/mock; blocking calls in async code.
   - Logs with secrets, tokens, full bodies, or unbounded metric labels.
   - Secrets or real data in code, fixtures, values files.
   - Unrelated changes, debug leftovers, commented-out code, TODO without Jira.
   - Deviations from the specs (docs/architecture.md, Google Doc appendix الف)
     not called out; anything marked ⚖ pending in AGENTS.md implemented without
     a recorded decision.
   - Outbound fetches that bypass the SSRF-safe fetcher.

4. **Fix** every ❌ you can fix safely, in new commits that follow the commit
   convention. Re-run step 2 after fixing.

5. **Report** to the user:
   - Gate results (exact pass/fail lines).
   - Remaining ❌ items you could not fix, with `file:line` and why.
   - Draft MR title + description filled from the matching template in
     `.gitlab/merge_request_templates/` (feature / bugfix / improvement), in
     Persian like the templates, with the Jira link placeholder kept if unknown.

Do not push, open the MR, merge or tag as part of this skill unless the user
explicitly asks after reading the report.
