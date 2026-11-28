---
paths:
  - "alembic/**"
  - "src/alembic/**"
  - "src/**/models.py"
  - "src/app/models/**"
  - "src/models/**"
---

# Database and migration rules

- One model change = one Alembic revision in the same MR. Exactly one head;
  if a branch appears, add a merge revision before the MR is merged.
- Generate with `make migration m="..."`, then **read and fix** the file:
  types, server defaults, nullable, indexes, constraint names, and a
  `downgrade()` that really reverses `upgrade()`. Autogenerate is a draft.
- Revision file name/id: `NNNN_<snake_desc>.py` with `revision = "NNNN"`,
  continuing the existing sequence.
- Naming convention comes from `models.BaseModel.metadata` (Postgres-native
  style used by the other services: `%(table_name)s_pkey`, `_key`, `_fkey`,
  `_check`, `_idx`). Never name constraints by hand differently, never remove
  the convention.
- Primary keys: UUID for entities exposed by id (`source`, `item`, `topic`);
  timestamps `timezone=True`, stored in UTC.
- Phase-1 tables. Names and some columns differ between the specs (⚖ pending,
  docs/STRUCTURE_GAP.md §۳): architecture.md uses `sources`, `source_runs`,
  `source_checkpoints`, `items` (+ an item-version table for real content
  changes); the Google Doc uses `source`, `crawl_run`, `item`. Do not create
  the first migration for these until the names are decided.
- Decided for phase 1: `topic`, `source_topic`, `item_topic` (`origin` in
  `source|manual|ai`) and `items.duplicate_of` (nullable self-FK, indexed) for
  cross-source duplicates.
- Required regardless: unique `(source_id, external_id)` on items; indexes (not
  unique) on `canonical_url` and `content_hash` for dedupe lookups —
  `(source_id, content_hash)` uniqueness is ⚖ pending; FK from
  items to sources **without** `ON DELETE CASCADE` (deleting a source keeps its
  items); indexes for the feed filters (`published_at`, `source_id`) and for the
  scheduler (`next_run_at` on enabled sources); GIN index for full-text search.
- The example `items` table that ships with the boilerplate collides with the
  spec's `items`; drop or rename it in its own migration before adding the real
  one.
- `jsonb` columns (`config`, `metadata`, `raw_data`, checkpoint `cursor`) are validated by a
  pydantic schema before write; never store unvalidated client dicts.
- Data migrations are separate revisions from schema migrations and must be
  idempotent. Large backfills are scripts (`scripts/`), not migrations.
- Zero-downtime: add nullable column → backfill → add constraint in a later
  release. Never rename/drop a column the running version still reads.
- `make migration-check` (Postgres) must report no drift before pushing.
- Migrations must never run concurrently. Alembic takes **no** lock by itself:
  `alembic/env.py` takes a Postgres advisory lock (`pg_advisory_lock`) around
  `run_migrations()` on the postgresql dialect, and in Kubernetes migrations run
  once in the Helm hook Job, not in every pod's entrypoint.
