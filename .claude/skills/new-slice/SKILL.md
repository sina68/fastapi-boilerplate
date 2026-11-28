---
name: new-slice
description: Scaffold a new business slice (e.g. source, topic, item, crawl_run) in the team-standard layout src/api/<slice>/ with router, schemas, models, repository, service, dependencies, metrics, migration and tests. Use when adding a new resource or API area.
---

# New slice: `$ARGUMENTS`

Follow AGENTS.md sections 2–3 exactly. Reference shape:
`notification-python/src/api/message/*` (class-based service/repository wired in
`dependencies.py`, per-slice `metrics.py`).

1. Read both specs for this slice — `docs/architecture.md` (data model §5,
   §7, §9, §13; API/search §14) and the Google Doc (الف.۳ data model, الف.۹ API) —
   and list fields, uniqueness, indexes, endpoints. If they disagree and
   docs/STRUCTURE_GAP.md §۳ has no recorded decision, or the spec is marked ⚠️,
   stop and ask before writing code.
2. Create `src/api/<slice>/`:
   - `models.py` — SQLAlchemy model on `models.BaseModel`, UUID pk,
     tz-aware timestamps, constraints named by convention.
   - `schemas.py` — `<Name>Create`, `<Name>Update`, `<Name>Out`, list
     response; length/size caps on every free-text field and list.
   - `repository.py` — `class <Name>Repository` taking `AsyncSession`.
   - `service.py` — `class <Name>Service` taking the repository (and other
     collaborators) in `__init__`; raises `core/exceptions.py` errors.
   - `dependencies.py` — `get_<slice>_repository`, `get_<slice>_service`.
   - `metrics.py` — API metrics set for this slice.
   - `router.py` — `APIRouter(prefix="/<slices>", tags=["<slice>"])`, metrics
     route class, `CurrentUser` / `AdminUser` guards.
3. Register the router in `utils/app.py` `add_api_routers`; import the model in
   `alembic/env.py`.
4. `make migration m="add <slice>"`, then read and fix the revision
   (`.claude/rules/migrations.md`).
5. Tests in `tests/<slice>/`: happy path per endpoint, 401, 404 (missing and
   other user's row where ownership applies), 422, 403 for admin-only routes,
   plus every business rule in the service.
6. New env vars → `Settings`, `.env.example`, `tests/conftest.py`, Helm values.
7. `make lint && make test`, then `/pre-push-review`.

If the repo still uses the old `src/app/` layout and the structure migration
MR has not landed, stop and ask the human whether to (a) wait for the
migration MR or (b) build this slice in the new layout alongside the old one.
