---
paths:
  - "src/connectors/**"
  - "src/processing/**"
  - "src/worker/**"
  - "src/adapters/http.py"
  - "tests/connectors/**"
  - "tests/processing/**"
---

# Connector, fetcher and processing rules

Sources: architecture.md §8, §10–§13, §16; Google Doc الف.۴–الف.۷.
Pattern for the registry: `translation`'s `providers/` (Protocol in `base.py`,
explicit factory map in `registry.py`, one package per implementation).

## Interface (⚖ pending: the two specs differ)

- architecture.md §8.1: `fetch(source, checkpoint) -> raw`, `parse(raw) -> items`.
- Google Doc الف.۴: `type`, `config_schema` (pydantic → JSON Schema for the panel
  form), `network_group`, `test(config)`, `fetch(config, cursor) -> (items, new_cursor)`.

Until the decision is recorded in docs/STRUCTURE_GAP.md §۳, the base class must
satisfy both, so neither choice forces a rewrite:

```python
class BaseConnector(Protocol):
    type: str  # "telegram" | "rss" | "atom" | "website"
    config_schema: type[BaseModel]  # validates source.config, drives the panel form
    network_group: str  # "domestic" | "egress" -> Celery queue (AGENTS.md §4)
    needs_browser: bool = False  # True routes to "<group>_browser" (Playwright)

    async def fetch(self, source: SourceConfig, checkpoint: Checkpoint | None) -> RawBatch: ...
    async def parse(self, raw: RawBatch) -> list[RawItem]: ...

    # test/preview = fetch + parse with a small limit, no persistence
```

`RawItem`: `external_id`, `url`, `title`, `content`/`content_html`, `summary`,
`author`, `published_at`, `metadata{}`, `raw_data{}`. `RawBatch` carries the
new checkpoint value; the worker stores it only after the items are committed.

## Connector rules

- Adding a source of an existing type = data only (panel/API). Adding a new type
  = new package + registry entry + `config_schema`; scheduler, storage, search
  and panel do not change. If they must, the interface is wrong: raise it in the
  MR.
- Connectors are fetch + parse only: no DB, no commits, no dedupe, no topic
  assignment. They run and are tested without FastAPI.
- `external_id` is stable per source (Telegram message id, feed GUID or
  canonical link). Never list position or fetch time.
- Incremental via checkpoint (last message id, ETag/Last-Modified). Bounded
  backfill; never crawl unbounded history.
- Fetch strategy order (architecture.md §8.5): structured API / RSS / sitemap →
  HTTP fetch → HTML extraction → Playwright. Playwright only for sources that
  cannot work without JavaScript; it runs on its own queue with explicit CPU and
  memory limits and is never the default.
- Per-site extraction config (selectors, date format) lives in `source.config`,
  validated by `config_schema`, separate from generic connector logic.
- Errors: `TransientError` (timeout, network, 429, 5xx → retried with backoff +
  jitter, bounded, honour `Retry-After`) vs `PermanentError` (invalid URL/config,
  other 4xx, parse failure → not retried). Never swallow exceptions.
- A structural change (page that should have posts returns none) is an error,
  not "0 new items". A run that genuinely finds nothing new is `succeeded`.
- Parse defensively: missing optional fields become `None`, one bad item is
  recorded and skipped.
- Telegram access method is an open decision (architecture.md §26.1; Google Doc
  proposes public `t.me/s/<channel>` with `?before=<id>` paging). Do not add
  Telethon or any account-based client without a recorded decision.

## Fetcher (`adapters/http.py`) — the only way out to the internet

- `http`/`https` only; resolve DNS once, block loopback, private, link-local,
  CGNAT, multicast, reserved and cloud-metadata ranges (IPv4 and IPv6), connect
  to the vetted IP, re-validate every redirect hop, cap redirects.
- Connect and read timeouts, maximum response size enforced while streaming.
- Per-domain rate limit (Redis token bucket, namespaced key with TTL) and
  per-domain concurrency; identified User-Agent from settings; `robots.txt`
  checked and cached per domain, overridable per source only with a recorded
  reason.
- Conditional GET (ETag / Last-Modified) for feeds and pages that support it.
- Proxy (if any) from settings, never hard-coded, never logged.

## Processing (`processing/`)

- Order: parse → normalize → validate → dedupe → persist.
- Normalization: whitespace, Unicode normalization, Persian ی/ي and ک/ك, ZWNJ,
  digits, diacritics/control chars; URL canonicalization (drop tracking params
  such as `utm_*`, normalize scheme/host/trailing slash); all dates to UTC
  (Jalali parsed explicitly). Keep the original text where normalization could
  lose meaning.
- Validation: valid source, valid URL, required fields present, sane date,
  content size cap, types.
- `content_hash` = SHA-256 of normalized content; it drives change detection
  (update + version row only when it changes).
- Pure functions, no I/O, exhaustively unit-tested.
