# Development log

Append-only record of decisions, work, and verification. Add new entries at the end; do not rewrite old entries.

## 2026-09-24 — Planning baseline

- Read the 2-page candidate brief. Recorded its hard requirements and a 2–3 hour scope in `docs/PLAN.md`.
- Chose 100 unique documents as a per-run target, with `document_number` as the upsert key; do not truncate or cap the lifetime table.
- Chose upstream pagination that ignores `count`/`total_pages`; stop at 100 unique documents or confirmed exhaustion. Chose a keyset cursor plus a 21-row query for the app's 20-row pages.
- Chose Python `psycopg` with parameterized SQL and TypeScript Drizzle. Kysely is TypeScript-side; it is not a Python database library.
- Reviewed `pursuit-map` patterns. Reuse bounded retries, `Retry-After`, error classification, simple text normalization, and run summaries. Skip its durable job orchestration and adaptive concurrency for this five-page run.
- Recommended Neon for an optional hosted DB preview, subject to rechecking current limits; local Postgres remains the default. Compared current official Neon, Supabase, and Render free-tier docs.
- **Verification:** extracted the assignment text from the supplied PDF and inspected the relevant `pursuit-map` modules. Federal Register docs confirm no API key is required. Live API probing could not run: this workspace's `curl` failed DNS resolution. No code or tests run.
- **Next:** establish the local stack, retry the one-page API probe from a network-enabled shell, then deliver the Stage 1 tracer bullet in `docs/PLAN.md`.

## 2026-09-24 — Pagination terminology

- Clarified that the assignment asks for pagination. A cursor/keyset is one retrieval strategy; JSON:API is an optional API response/query specification that can represent pagination links and cursor parameters.
- Kept a small `{ items, nextCursor }` response contract in the plan because the brief does not require JSON:API's resource envelope.
- **Reference:** [JSON:API 1.1 pagination](https://jsonapi.org/format/#fetching-pagination).

## 2026-09-24 — Local tooling and repo shape

- Confirmed Node `v24.21.0`, `uv 0.10.6`, Docker `29.4.0`, and `psql 17.7` are available.
- Proposed `apps/web`, `pipelines/ingest`, and root `compose.yaml`; keep Next/Drizzle and Python/psycopg toolchains independent, with Drizzle migrations as the schema source.
- **Verification:** version commands returned successfully. No services started and no tests run.

## 2026-09-24 — Handoff requirements

- Added the brief's GitHub/zip submission choices and technical-discussion preparation to the plan's final checklist.
- **Verification:** checked these against the submission section of the supplied brief. No delivery action taken.

## 2026-09-24 — API format and Python SQL tooling

- Clarified that `{ items, nextCursor }` is a custom response, not JSON:API. JSON:API has its own top-level document members and `links.next`; it can still use cursor pagination.
- Recorded SQLAlchemy Core as the Python query-builder analogue to Kysely. Kept direct parameterized Psycopg SQL as the plan for the small ingest so the SQL stays explicit and the ORM remains out of the Python path.
- **References:** [JSON:API 1.1](https://jsonapi.org/format/#fetching-pagination), [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/), [Psycopg parameter binding](https://www.psycopg.org/psycopg3/docs/basic/params.html).

## 2026-09-24 — JSON:API endpoint direction

- User chose JSON:API compliance or a directionally compliant design. Scoped implementation to JSON:API 1.1 collection reads at `GET /api/documents`.
- Replaced the custom envelope with `data` resources, `application/vnd.api+json`, standard `filter`/`page` parameter families, stable `sort`, self/next pagination links, and JSON:API errors.
- Kept writes, relationships, and `include` out of scope; none support the requested list page. Increased the serving-stage estimate by five minutes.
- **Verification:** compared the response and pagination shape with the JSON:API 1.1 spec. No app code or tests run.

## 2026-09-24 — Parquet archive and diagnostic sinks

- Chose immutable per-page Parquet snapshots under `data/raw/federalregister/run_id=<id>/`; retain the raw document object in `payload_json` and keep normalized serving records in Postgres.
- Added root `.gitignore` rule `/logs/`. Planned append-only `logs/ingest.jsonl` via Python Loguru and `logs/web.jsonl` via Pino. Interpreted “pinio” as Pino.
- Kept `docs/devlog.md` for human decisions and milestones; JSONL is machine-readable runtime feedback. Agent failure handoffs should name the run/request ID, log path, error class, and matching Parquet page.
- **References:** [Loguru JSON serialization/file sink](https://loguru.readthedocs.io/en/stable/api/logger.html), [Pino file transport](https://github.com/pinojs/pino/blob/main/docs/transports.md).
- **Verification:** checked official docs for JSON serialization and append defaults; reviewed `.gitignore`. No runtime data or tests run.

## 2026-09-24 — Confirm JSON:API scope

- Committed to JSON:API 1.1 response shapes for the supported read-only documents collection. The API returns `data` resources and top-level `links`; it will not use a custom `{ items, nextCursor }` envelope.
- Clarified that JSON:API provides the pagination-link and `page` parameter conventions; cursor encoding and filter semantics remain API-specific. The resource `id` carries `document_number`, so the same field need not be duplicated in attributes.
- Clarified the Python query-builder choice: SQLAlchemy Core is the closest Kysely analogue; direct Psycopg SQL remains simpler for this fixed ingest. Psycopg is the database driver.
- **Verification:** reviewed the planned response example and scope against [JSON:API 1.1](https://jsonapi.org/format/). No app code or tests run.
