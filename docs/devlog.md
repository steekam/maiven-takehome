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

## 2026-09-24 — Federal Register schema and ingest design

- Pulled the public OpenAPI 3.0.0 document into `pipelines/ingest/spec/federal-register.openapi.json`. It lists 14 GET routes across published documents, public inspection, agencies, images, and suggested searches. It describes query/component enums, but each success response only says “200 Success”; there are no response models or auth scheme.
- Confirmed the EPA Rules query parameters live: `conditions[agencies][]=environmental-protection-agency`, `conditions[type][]=RULE`, `order=newest`, and `per_page`. The optional repeated `fields[]` parameter can request fields such as `effective_on`.
- A small live page returned `description`, `count`, `total_pages`, `next_page_url`, and `results`; result documents contain agency objects and nullable `abstract`/`excerpts`. The next URL preserves filters and supplies an opaque `search_after_cursor`. Ignore the reported totals and follow that URL.
- Observed a `per_page` edge: a request for 2 returned 2 rows; a request for 1 returned 20, despite the schema's minimum of 1. A configured 100-row default matches the run target and documented 1,000 maximum; keep the anomaly in a fixture. Responses included `x-request-id`; sampled headers had no rate-limit fields. No quota is published in the developer guide.
- Planned the ingest boundary: a reusable synchronous HTTPX client for the `/documents.json` search contract; an EPA Rules query preset for agency/type/date/order/fields; a workflow for page traversal, run cap, deduplication, Parquet archive, normalization, and DB upsert. Keep request transport sequential and retry/timeouts configurable.
- The official REST API guide also limits pagination to the first 2,000 search results; use a date filter if a future ingest needs a wider source window. Current target is the newest 100 unique documents.
- **Verification:** `jq` parsed the downloaded schema; two small EPA Rules probes confirmed filter encoding, `fields[]`, result envelope, `next_page_url`, and the `per_page=1` anomaly. No code or tests run.

## 2026-09-24 — Raw response archive format correction

- Superseded the earlier Parquet/PyArrow archive proposal. Keep each received Federal Register HTTP response in run-scoped `data/raw/federalregister/run_id=<id>/responses.jsonl`, with run/request IDs, page and attempt numbers, fetch time, request method/URL, status, selected response headers, UTF-8 response body, and a SHA-256 hash of the exact pre-parse body bytes. Verify the hash by re-encoding the stored body as UTF-8.
- Keep this source archive separate from the gitignored `logs/` JSONL diagnostic sinks. Diagnostic events carry correlation IDs and operational details but no source body. Normalized application records remain in Postgres. Do not add PyArrow solely for archiving.
- This is a design decision only; no implementation or tests run.

## 2026-09-24 — Reliability-first stretch priorities

- Prioritized the stretch path as: (1) resume/idempotency with durable run status and the API-provided next-page URL checkpoint, transactionally advancing it with document upserts; (2) JSONL response/page traceability with a manifest linking archive records to persisted document IDs and outcomes; (3) fixture-driven restart, cursor, retry, and malformed-response verification.
- Keep cursor chains sequential and allow only one active worker per run. A resume must match the original query fingerprint. A failed page leaves the checkpoint in place; replay may append another response record but unique `document_number` upserts prevent duplicates. The structured run summary should expose page/archive references, persisted IDs/outcomes, pages fetched, inserted/updated counts, retries, and failures.
- Keep JSON:API `self`/`next`, stable success `meta`, and error documents in the required path; test following cursors without duplicate records. Rank a hosted seeded walkthrough after goals 1–3 and UI polish.
- This is a planning update only; no implementation or tests run.

## 2026-09-24 — Recovery design edge cases

- Keep the 100-unique-document run cap independent of the configured source page size: archive the full response, persist only through the remaining unique allowance, and atomically mark the run succeeded/clear its next-page checkpoint when the cap or source end is reached.
- Commit page records, archive manifest, counters, checkpoint, and terminal run state together. The run summary links all archived attempts (including failed/retried responses) by request ID and path/hash; only successfully persisted pages have document outcome links. Upstream `x-request-id` is optional.
- Clarified JSON:API error documents: top-level `jsonapi`, `meta.request_id`, and `errors` with `status`, `title`, `detail`, and `source.parameter`; no `data` member.
- This is a planning refinement only; no implementation or tests run.

## 2026-09-24 — Ingest model view and assessment brief

- Moved the takehome assessment PDF into `docs/` so the source brief lives with the plan and is tracked.
- Added conceptual source DTO, raw response archive, normalized document, run, page, and run-document schemas to the plan, with an entity diagram and page transaction flow. The design still separates full raw source bodies, gitignored diagnostics, and normalized Postgres records.
- This is a design/documentation update only; no implementation or tests run.

## 2026-09-24 — Archive encoding and run-wide deduplication

- Refined the raw JSONL body representation to preserve every response byte: store valid UTF-8 bodies as text and fall back to base64 for invalid UTF-8, with an explicit encoding marker. Hash the original response bytes before parsing.
- Made `ingest_run_documents` unique on `(run_id, document_number)` so the persistence manifest enforces the per-run unique-document cap. Build summaries from every raw archive attempt, then join successful request IDs through the page and document manifest.
- No implementation or tests run.

## 2026-09-24 — Page size, agency JSONB, and Drizzle Kit

- Superseded the earlier 100-unique-document run cap. The EPA preset requests `per_page=100` on each source page and follows all `next_page_url` links until absent/null, subject to the API's documented 2,000-result pagination limit. Keep run-wide deduplication and upserts; do not truncate an unexpectedly larger response page.
- Reaffirmed the source agency objects as an `agencies jsonb` array on `documents`; no separate agency catalog. For a future agency filter, JSONB containment (`agencies @> '[{"slug":"…"}]'::jsonb`) can use a GIN index. Defer the index for this small EPA-only dataset; a partial EPA index would likely cover nearly every row. Partial indexes also require a query predicate that implies the index predicate at planning time, which parameterized dynamic filters do not provide.
- Added Drizzle Kit to the planned setup: `apps/web/src/db/schema.ts` is the Postgres schema source; configure `drizzle.config.ts`, commit generated SQL under `apps/web/drizzle/`, and apply migrations with `drizzle-kit migrate` before Python ingest. Python remains a parameterized Psycopg client of the shared schema.
- Updated `docs/PLAN.md`; design only. **References:** [PostgreSQL JSONB indexing](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING), [PostgreSQL partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html), [Drizzle Kit generate](https://orm.drizzle.team/docs/drizzle-kit-generate), [Drizzle Kit migrate](https://orm.drizzle.team/docs/drizzle-kit-migrate).
- No implementation or tests run.

## 2026-09-24 — Clarify the 100-document run target

- Corrected the latest pagination interpretation: each run ingests up to 100 unique `document_number`s, or fewer if the source is exhausted. This is a per-run target, not a 100-row lifetime database cap. `per_page=100` remains an independent upstream request size; duplicates do not count toward the target. Archive the full fetched response, but persist only the remaining unique allowance for that run.
- A restart resumes the latest incomplete run by default when its query fingerprint matches, starting from its last committed `next_page_url`. `--new-run` deliberately starts a separate run. A completed run remains complete; the documents table is never truncated, so future runs can retain or update prior records.
- Updated `docs/PLAN.md` to move run/checkpoint state into the baseline. This supersedes the immediately prior decision to fetch every page until source exhaustion without a run-wide target, while retaining the JSONB agency array and Drizzle Kit migration design.
- Design only; no implementation or tests run.
