# Maiven takehome plan

- **Status:** planning and reconnaissance; OpenAPI snapshot and request probe captured, implementation not started
- **Updated:** 2026-09-24
- **Time box:** 2–3 hours, matching the candidate brief

## Goal

Show one clear path from the Federal Register to a searchable page. Keep the work small enough to explain in a technical discussion. The brief values approach and core capability over production polish.

## Acceptance checklist

- [ ] Python ingest fetches EPA Rules and stores up to 100 unique documents per run; the database can keep growing across runs.
- [ ] Pagination does not rely on `count` or `total_pages`.
- [ ] Re-running the ingest does not duplicate documents or delete existing rows.
- [ ] Every fetched response has a run/request trace and SHA-256 in the separate raw JSONL archive.
- [ ] `GET /api/documents` returns JSON:API 1.1 collection documents with newest publication dates first, an inclusive publication-date filter, and case-insensitive text search.
- [ ] The API returns 20 documents per page with valid JSON:API `self`/`next` links and a consistent top-level `meta`; errors use `errors` without `data`.
- [ ] One page displays documents and wires up filters, search, and Load more.
- [ ] Tests cover text cleaning and ingest re-run behavior.
- [ ] README explains requirements, setup, how to run, and what more time would change.

## Deliverable invariants

1. `document_number` is the stable source identity and has a unique database constraint.
2. Ingest writes use an upsert inside a transaction; never clear the table before loading. A later run may update a known document without removing other rows.
3. Archive every received HTTP response as a new line in the run-scoped raw JSONL archive before transforming it. Include run/request provenance and a SHA-256 hash of the response body. Normalize serving fields into Postgres and never overwrite an older archive.
4. The upstream run stops after 100 unique documents or a confirmed end of results. `count` and `total_pages` are informational only.
5. The serving API sorts by `(publication_date DESC, document_number DESC)` for deterministic ties. A changed search or date filter starts pagination over.
6. Network failures and malformed responses are visible as failed runs. Do not log and skip them as if ingest succeeded.
7. Runtime diagnostics are append-only JSONL files under root `logs/`, ignored by Git. Keep source bodies out of diagnostics; use run/request IDs to connect events to the separate raw response archive.

## Proposed shape

```text
Federal Register API
        │ one sequential page request at a time
        ▼
Python CLI ── raw HTTP response ──> run-scoped JSONL archive
    │ clean + normalize
    └── psycopg parameterized SQL ──> PostgreSQL documents + run state (stretch)
                                          │
                             Next.js App Router + Drizzle
                             JSON:API GET (20 + cursor link)
                                          │
                                          ▼
                             list + filters + Load more

Python Loguru ──> logs/ingest.jsonl       Pino ──> logs/web.jsonl
                         (append-only, gitignored)
```

Keep the baseline Postgres schema small: `documents` with `document_number`, `title`, `publication_date`, `effective_on`, `abstract`, `agencies` JSON, `html_url`, and timestamps if useful. The reliability stretch adds small `ingest_runs` and `ingest_run_pages` tables for run state, source checkpoints, and archive-to-record traceability; it does not add a general job engine or normalized agency catalog.

Append one record per received HTTP response to `data/raw/federalregister/run_id=<id>/responses.jsonl`. Each record should include `run_id`, a unique `request_id`, page and attempt numbers, fetch time, method and requested URL, HTTP status, selected response headers (including the upstream `x-request-id` when present), `content_sha256`, and the original response body as UTF-8 text. Decode as UTF-8 strictly and hash the response body bytes before JSON parsing; re-encoding the stored body as UTF-8 must reproduce the hash. Archive successful and unsuccessful HTTP responses before status classification or retry so a failed run can be inspected. A transport failure with no response belongs in diagnostics only. Keep this durable source archive separate from `logs/`.

### Resumable page transaction

The reliability stretch stores a run's status (`running`, `failed`, or `succeeded`), immutable query fingerprint, target, counters, failure class, and `next_page_url` checkpoint in `ingest_runs`. The checkpoint is the URL to fetch next; initialize it with the first request URL. After a page is archived, validated, and normalized, use one Postgres transaction to upsert only the records within the remaining unique-document allowance by `document_number`, write its `ingest_run_pages` manifest (request ID, archive path/hash, page number, and persisted document IDs/outcomes), and update counters/checkpoint/status. For a nonterminal page, set the checkpoint to the API-provided `next_page_url`. If the source has no next link or the unique-document target is met, clear the checkpoint and mark the run `succeeded` in that same transaction. Preserve the full fetched response, including any unused records and returned next link, in the raw archive. Never derive a cursor from `count` or `total_pages`.

Fetch one page at a time, following the API's cursor chain in order. If the process fails before the page transaction commits, the checkpoint still points to that page; resume refetches it, and the unique-key upsert prevents duplicates. If commit succeeds, page records, counts, manifest, and the next checkpoint or terminal status are durable together. A resume must match the original query fingerprint. Archive append is intentionally outside the DB transaction: an interrupted page may leave an extra archived attempt, but it cannot advance the checkpoint or skip persistence. Use a per-run Postgres advisory lock so a stale `running` run can resume after a process exits, while two workers cannot advance the same cursor chain concurrently.

```mermaid
sequenceDiagram
    participant FR as Federal Register
    participant CLI as Ingest CLI
    participant Archive as Raw JSONL archive
    participant PG as Postgres
    CLI->>FR: GET checkpoint URL (sequential)
    FR-->>CLI: Response + next_page_url
    CLI->>Archive: Append body, request metadata, SHA-256
    CLI->>PG: Transaction: upsert docs + manifest + checkpoint/status
    alt Commit succeeds
        PG-->>CLI: Commit page and checkpoint/status together
        CLI->>FR: Fetch next URL if checkpoint is non-null
    else Process/DB failure before commit
        PG-->>CLI: Roll back; checkpoint remains on this page
        Note over CLI,PG: Resume refetches this page; document_number upserts remain idempotent
    end
```

Write structured events to `logs/ingest.jsonl` and `logs/web.jsonl`. Each line gets a timestamp, level, service, event name, and `run_id` or `request_id`, plus the relevant page, status, duration, count, retry delay, or error class. Never log the full source payload; the raw response archive owns that detail. Ignore `logs/` in Git; keep `data/raw/` as a separate archive path whose persistence/retention is an explicit project choice.

### Repo shape

```text
apps/web/                 Next.js App Router: API, page, Drizzle schema/migrations
pipelines/ingest/
  pyproject.toml           uv project; independent Python environment
  uv.lock
  spec/
    federal-register.openapi.json
  src/maiven_ingest/
    cli.py                 parse run options; set exit status
    config.py              environment config and validation
    federal_register/
      client.py            HTTP transport, query encoding, retry, page envelope
      models.py            typed search options and minimal response envelope
    sources/
      epa_rules.py         EPA + Rule query preset
    workflow.py            cap, resume checkpoint, and ingest orchestration
    archive.py             append raw HTTP responses to run-scoped JSONL
    normalize.py           raw document to serving row
    store.py               parameterized Postgres upsert
  tests/
    fixtures/
    test_client.py
    test_normalize.py
    test_workflow.py
compose.yaml              local PostgreSQL
data/raw/                 run-scoped JSONL Federal Register response archive
logs/                     local JSONL diagnostics; ignored by Git
docs/                     plan, append-only devlog, README links
```

Keep the two toolchains independent. Run migrations from the web app before ingesting; the Python CLI uses the same Postgres columns through parameterized SQL. Skip Turborepo or a cross-language task runner unless setup proves it necessary.

Keep the HTTP client generic for the Federal Register document-search endpoint, with a small EPA Rules query preset above it. The client owns URL/parameter construction, the reusable HTTP session, timeout/retry policy, status classification, response-envelope validation, and following a same-origin `next_page_url`. The EPA preset owns agency/type/date/order/field filters. The workflow owns the 100-unique-document cap, deduplication, archive-before-transform order, and persistence. Do not generate a broad SDK for all API paths: the OpenAPI spec leaves success response bodies undefined.

Use a synchronous `httpx.Client` for the first version and keep page requests sequential. Its client-level configuration supports a reusable base URL, headers, connection pooling, and timeouts; retry behavior for `429`/`5xx` and `Retry-After` remains our explicit client policy. [HTTPX clients](https://www.python-httpx.org/advanced/clients/) and [timeouts](https://www.python-httpx.org/advanced/timeouts/) document those controls. The public API has no key requirement; the OpenAPI file lists no authentication scheme.

### Federal Register API overview

The checked-in [OpenAPI snapshot](../pipelines/ingest/spec/federal-register.openapi.json) is OpenAPI 3.0.0, served relative to `/api/v1/`. Its paths are all `GET` operations:

| Area | Paths |
| --- | --- |
| Published documents | `/documents.{format}`, `/documents/{document_number}.{format}`, `/documents/{document_numbers}.{format}`, `/documents/facets/{facet}`, `/issues/{publication_date}.{format}` |
| Public inspection documents | `/public-inspection-documents.{format}`, `/public-inspection-documents/current.{format}`, `/public-inspection-documents/{document_number}.{format}`, `/public-inspection-documents/{document_numbers}.{format}` |
| Reference data | `/agencies`, `/agencies/{slug}`, `/images/{identifier}`, `/suggested_searches`, `/suggested_searches/{slug}` |

The useful shared schemas describe inputs/enums, not document response models: `Format`, `DocumentField`, `DocumentType`, `Agency`, `FrDate`, `FrYear`, `Facet`, `Section`, `Topic`, `President`, `PresidentialDocumentType`, `PublicInspectionDocumentField`, and `SuggestedSearch`. The EPA slug is `environmental-protection-agency`; the document type value is `RULE`. The schema includes date ranges, full-text search, agency/type lists, `per_page` (documented 1–1000, default 20), `page`, `order`, and optional `fields[]`. It also describes effective-date, docket, RIN, section/topic, CFR, significance, and location filters. Every successful operation declares only “200 Success”, with no response schema.

The in-scope search request is `GET /api/v1/documents.json` with `conditions[agencies][]=environmental-protection-agency`, `conditions[type][]=RULE`, `order=newest`, and `per_page` configured independently from the ingest run cap. Optional publication-date bounds and repeated `fields[]` values map directly to the documented parameters. `fields[]` can include `effective_on`; the default response sample did not include it. If the EPA profile sends `fields[]`, list every field needed by the serving row and archive each returned object unchanged before normalization.

Keep three config boundaries separate:

| Config | Options |
| --- | --- |
| `FederalRegisterClientConfig` | Base URL, connect/read timeout, default headers/User-Agent, retry budget, backoff bounds. No API-key option. |
| `DocumentSearch` | Agency slugs, document types, optional term/date bounds, order, `per_page` (1–1000 per schema), optional field projection. Serialize arrays as repeated bracketed keys. |
| `IngestRunConfig` | `max_unique_documents=100`; one in-flight request. This cap is independent of API page size and not sent as an API parameter. |

The live response envelope observed for this query is `{ description, count, total_pages, next_page_url, results }`. Each result has a `document_number`, title/type, publication date, links, agencies as objects, and optional nullable `abstract`/`excerpts`. `next_page_url` is an API-provided URL with the query retained and an opaque `search_after_cursor`; use it verbatim after checking the origin. Do not construct the cursor or decide completion from `count`/`total_pages`.

The probe found a page-size inconsistency: `per_page=2` returned two rows, while `per_page=1` returned twenty rows despite the schema's minimum of one. The EPA Rules profile should default to 100 rows per upstream request (the run still persists at most 100 unique documents), and tests should keep a fixture for the `per_page=1` anomaly. Two sampled responses had no rate-limit headers; one returned `x-request-id`. The API guide does not publish a request quota, so keep one in-flight request and treat `429`/`Retry-After` handling as polite client behavior, not a published service requirement.

## Decisions and assumptions

| Topic | Plan | Reason / follow-up |
| --- | --- | --- |
| “A run should ingest 100 documents” | Treat 100 as a per-run target of unique documents, not a lifetime database cap. Stop earlier only when results are exhausted. | Put this in a README “Assumptions” section: “Each run fetches up to 100 distinct Federal Register documents. This is a per-run target, not a lifetime database cap or 100 new-to-database rows. Re-runs upsert matching documents, and existing rows are retained.” |
| Source pagination | Request `per_page=100` by default (configurable within the documented 1–1000 range), follow `next_page_url` as returned, and count unique document numbers. Stop at 100 unique documents or when the next link is absent/null. | API response links carry an opaque `search_after_cursor`; do not synthesize cursor values. Ignore `count` and `total_pages`. The observed `per_page=1` anomaly is covered by a client fixture. |
| Do we need an extra upstream page? | No. An absent/null `next_page_url` marks exhaustion; stop earlier at 100 unique documents. | The API provides the continuation link. Do not add a confirmation request or rely on totals. |
| Raw source archive | Append every received HTTP response to `data/raw/federalregister/run_id=<id>/responses.jsonl` before status classification, retry, or normalization. Each line includes run/request IDs, page/attempt, fetch time, method/URL, status, selected response headers (including upstream request ID when present), response-body SHA-256, and the response body as UTF-8 text. | Preserves request/response evidence for replay and diagnosis if parsing, normalization, or the DB write fails. A Postgres page manifest links successful archived responses to persisted document IDs/outcomes. This is separate from gitignored diagnostic JSONL under `logs/`; no PyArrow dependency is needed. |
| Runtime logs | Use Loguru in Python and Pino in the Next.js server for JSONL append sinks at `logs/ingest.jsonl` and `logs/web.jsonl`. Add `/logs/` to root `.gitignore`. | `pinio` interpreted as Pino. Keep human decisions in `docs/devlog.md`; logs hold machine events only. Do not log raw payloads. |
| API format | Follow JSON:API 1.1 for the supported read-only documents collection: `application/vnd.api+json`, top-level `data`, resource objects (`type: documents`, `id: document_number`, `attributes`), top-level `links.self`/`links.next`, stable `meta`, and JSON:API `errors`. | Do not return a custom `{ items, nextCursor }` envelope. This is a scoped read API; writes, relationships, `include`, and compound documents are out of scope. Keep `agencies` as an attribute. |
| Media negotiation | Return `Content-Type: application/vnd.api+json` and honor JSON:API's `Accept` media-type rules for the supported representation. | No extensions or profiles are needed. Keep negotiation small but spec-correct for the media types and parameters the endpoint supports. |
| Filters and pages | Use `filter[publication_date][gte]`, `filter[publication_date][lte]`, `filter[q]`, `page[size]`, and `page[cursor]`. Default `sort=-publication_date,-document_number`. | JSON:API reserves these query parameter families. Filter meaning remains specific to this API. Enforce a maximum page size of 20. |
| “Fetch the next 20” | Use keyset/cursor pagination and expose the next request as top-level `links.next`. Query 21 rows; set `links.next` only when row 21 exists, otherwise set it to null. | JSON:API defines pagination links and reserves the `page` parameter family; it does not prescribe cursor encoding. No `COUNT(*)` or total needed. |
| Cursor sort key | Encode the last visible `(publication_date, document_number)` pair in `page[cursor]`. Carry the same filters and sort in the next link. | This API-specific cursor gives unique, stable ordering and avoids offset shifts when new documents arrive. |
| Text cleaning and search | Trim and collapse whitespace in title/abstract; preserve agency objects as JSON. Search title and abstract with case-insensitive `ILIKE`. | Simple, visible normalization and search; enough for roughly 100 rows. |
| Date filter | Inclusive `filter[publication_date][gte]` and `filter[publication_date][lte]` on `publication_date`; reject invalid dates or lower bound after upper bound with 400. | JSON:API query family; no timezone conversion for date-only fields. |
| Database access | Python uses `psycopg` 3 with parameterized SQL, no Python ORM. TypeScript uses Drizzle for schema/migrations and typed queries. | SQLAlchemy Core is the closest Python analogue to Kysely when a composable expression/query builder is wanted; direct Psycopg SQL is leaner for this small fixed ingest. Psycopg is the driver, not a query builder. See [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/) and [Psycopg parameters](https://www.psycopg.org/psycopg3/docs/basic/params.html). |
| Client behavior | Start with sequential page requests, configurable timeout and retry budget, and bounded retries for timeouts, 408, 429, and 5xx. Respect `Retry-After`; fail fast on other 4xx and invalid payload envelopes. | The API publishes no quota in its schema/guide. One in-flight request is enough for this run. Log status, latency, upstream `x-request-id` when present, retries, and terminal error class. |
| UI | Single responsive list page; search, two date inputs, result count for the current page, and Load more. Use shadcn Button/Input if setup stays quick; native date inputs are fine. | Meets the assignment without spending time on a component library showcase. |
| Local database | Start with PostgreSQL from Docker Compose and one documented setup command. | Docker and `psql` are available. Keep hosting out of the critical path. See optional preview note below. |

### JSON:API collection shape

```text
GET /api/documents?filter[publication_date][gte]=2026-01-01&filter[publication_date][lte]=2026-09-24&filter[q]=water&sort=-publication_date,-document_number&page[size]=20&page[cursor]=<opaque>
Accept: application/vnd.api+json

{
  "jsonapi": { "version": "1.1" },
  "links": { "self": "...", "next": "..." /* or null */ },
  "meta": { "request_id": "...", "page": { "size": 20, "hasMore": true } },
  "data": [
    {
      "type": "documents",
      "id": "2026-12345",
      "attributes": {
        "title": "...",
        "publication_date": "2026-09-24",
        "effective_on": null,
        "abstract": "...",
        "agencies": [],
        "html_url": "..."
      }
    }
  ]
}
```

Respond with `Content-Type: application/vnd.api+json` and handle `Accept` negotiation for the supported representation. The database query fetches 21 matches in the requested order. Return the first 20; use the extra row to decide whether `links.next` exists. The next URL carries the cursor from the final returned row, not the extra row, plus the active filters and sort. Keep the success document shape stable, including `jsonapi`, `links.self`, nullable `links.next`, `meta.request_id`, `meta.page.size`, and `meta.page.hasMore`. Return invalid-parameter failures with top-level `jsonapi`, `meta.request_id`, and JSON:API `errors` containing `status`, `title`, `detail`, and `source.parameter`, with no `data` member. Keep the API spec-shaped within its read-only scope; do not claim support for unimplemented JSON:API operations.

## Execution plan

| Stage | Time | Work | Exit check |
| --- | ---: | --- | --- |
| 0. API contract | 10 min | Complete: save the OpenAPI snapshot, review endpoint/query schemas, and probe EPA Rules with a small page. Record that response bodies are undocumented, pagination uses `next_page_url`, and no quota headers were observed. | Request, response-envelope, and retry assumptions are recorded. |
| 1. Ingest tracer bullet | 40 min | Scaffold the uv project and configure the HTTP client. Get one representative EPA Rule through typed query → source page → raw response JSONL → normalization → Postgres upsert. | One response is archived with provenance/hash and one row is upserted in local Postgres. |
| 2. Complete ingest path | 35 min | Add next-link iteration, the 100-unique-document cap, bounded retry classification, append-only response archives, and Loguru run events. | Two fixture runs leave row count stable and append separate run archives; failures include a run ID and error class. |
| 3. Serve and display | 55 min | Add the JSON:API collection/resource envelope, media negotiation, inclusive date filters, case-insensitive search, stable cursor ordering, pagination links/errors, Pino events, and the list UI. | API and UI support search, filters, and Load more; request events are correlated. |
| 4. Required checks and handoff | 30 min | Add focused tests, write README, run the full local path twice, review logs and git diff, and note known limits. | Required tests pass; README setup works from a clean local database; no unrelated files are committed. |

Total planned time: 170 minutes, leaving 10 minutes of the 3-hour ceiling for setup friction. Work starts with the ingestion client and its source contract. If the baseline runs long, cut visual polish and hosting first; preserve ingest, idempotent writes, JSON:API collection contract, required tests, and README. If there is one stretch slice, choose reliability goals 1–3 below before optional pagination polish or deployment.

## Reliability-first stretch goals

The 170-minute plan is the assignment baseline. If a stretch slice fits, prioritize these first three in order; do them before a hosted demo or visual polish. The fourth item strengthens a required API contract. Treat the fifth as optional presentation work.

1. **Resume and prove idempotency.** Add minimal `ingest_runs` state: status, query fingerprint, target, next-page URL checkpoint, counters, and failure class. Resume a failed/interrupted run by ID only when its query fingerprint matches. Advance the source-provided checkpoint in the same transaction as page upserts and the page manifest. Upsert on the Federal Register `document_number`. Keep a run single-worker and each cursor chain sequential. Prove restart after a committed page neither duplicates nor skips source records.
2. **Link the raw archive to persisted records.** Keep one JSONL response record per HTTP attempt with run ID, request ID, page/attempt, requested URL, fetch time, status, optional upstream `x-request-id`, and SHA-256. `ingest_run_pages` links each successfully persisted page's request ID, archive path/hash, and document IDs/outcomes. A structured run summary event in `logs/ingest.jsonl` links every archived attempt by request ID and archive path/hash, and links successful pages to persisted records. Report pages fetched, records inserted/updated, retries, and failures without copying source bodies into diagnostics.
3. **Prove failure and recovery with recorded fixtures.** Cover opaque cursor progression, duplicate IDs across pages, restart/resume, timeout/429/5xx retry behavior, malformed JSON, and invalid/missing envelopes. Assert retries stay bounded and sequential, failed pages do not advance the checkpoint, and run summaries carry the error class and request/archive references.
4. **Verify JSON:API pagination end to end.** Keep valid `links.self` and `links.next`, consistent success `meta`, and top-level JSON:API errors with no `data`. Exercise a client that follows the returned cursor links and assert adjacent pages contain no duplicate records. The endpoint's base pagination contract remains part of the baseline.
5. **Make a live walkthrough only after reliability work.** Deploy the app with a seeded dataset and prepare a short demo that runs one ingest, follows the run summary to archived pages and persisted records, then shows those records in the UI. Skip this if deployment setup competes with goals 1–3.

## Verification and observability

- Keep one recorded, small EPA Rules probe for the actual `results` shape, agency shape, dates, ordering, pagination URL, status, and headers. Do not load-test a public API.
- Test request serialization with repeated `conditions[agencies][]`, `conditions[type][]`, and optional `fields[]` keys. Check date bounds and `per_page` against the OpenAPI limits; keep the observed `per_page=1` response anomaly in the client fixture.
- Use fixture pages to test `next_page_url` traversal, same-origin checking, unique `document_number` counting, the 100-document cap, and duplicate IDs across pages. Ignore `count`/`total_pages`.
- Test the retry classifier separately: transport timeout/connection failure, 408, 429 with delta/date `Retry-After`, 5xx, permanent 4xx, malformed JSON, and missing/invalid page envelope. Retries stay bounded and serial.
- Emit one structured run summary with `run_id`, pages fetched, unique documents seen, rows inserted/updated, retries, duration, final status, and failure class. In the reliability stretch, include page request IDs, archive paths/hashes, and document IDs/outcomes so the summary can be followed into raw JSONL and Postgres.
- Parse each raw archive line as JSON, re-hash its decoded response body bytes, and compare the body and request metadata with the fixture. Confirm later runs use new run-scoped paths and leave earlier archives unchanged.
- In the resumability stretch, inject a failure after one page commit, restart the same run, and compare the final persisted `document_number` set with the fixture's expected set. Assert the committed page is not duplicated or skipped, its checkpoint advances atomically, and a query-fingerprint mismatch prevents resume.
- Follow `links.next` in a JSON:API client fixture; check each page's stable `meta`, `links.self`, error-document structure, and cross-page duplicate absence.
- Check the run summary's page manifest: each successful page points to its JSONL response record/hash and the `document_number` rows persisted from that response; transient/malformed attempts still point to their archived request IDs, paths, hashes, and failure classes.
- Parse each diagnostic JSONL line as JSON. Confirm a second run/request appends lines, each event has a correlation ID, and source bodies stay in the raw archive rather than logs.
- Test `clean_text` with whitespace and markup/entity examples that the implementation actually handles.
- Test re-run behavior against Postgres: ingest the same fixture twice, assert one row per `document_number`, and assert a previously stored unrelated row remains.
- Verify the route's media type negotiation and JSON:API structure with no filters, each filter alone, combined filters, invalid dates, and a second cursor page. Confirm `links.next` carries filters and no rows repeat across adjacent pages in a static fixture.
- Run the UI once with results, no results, loading, and API failure. Confirm it reads `data` and follows `links.next`; changing filters resets the list and current link.
- Record the exact verification command and result in the devlog for each completed stage.
- When handing a failure to an agent, include the command, run/request ID, JSONL file path, relevant event/error class, and a small log excerpt. Have the agent inspect those events and the matching raw response record; do not paste entire source payloads into the diagnostic log or prompt.

## Reuse from `pursuit-map`

Borrow the small ideas from [`http_client.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/http_client.py) and [`normalize.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/normalize.py): classify transient vs permanent errors, respect `Retry-After`, trim/collapse display text, and preserve raw values where useful. The bulk runner and supervisor are useful reference material, but adaptive concurrency probes, a circuit breaker, durable job leases, and a full provenance ledger exceed this assignment. Keep the resumability stretch to one run checkpoint and a page manifest.

## Optional hosted preview

Keep the default demo local. If the app is complete and there is time for a public preview, Neon is a good first Postgres candidate: its current free plan lists 100 CU-hours per project/month and 0.5 GB storage, with compute scaling to zero after five idle minutes. That can add a cold start. Supabase also offers free Postgres with 500 MB, but its free projects pause after a week of inactivity. Render's free Postgres expires after 30 days, so it is a poor fit for a preview expected to remain available.

Check current limits before creating a hosted database: [Neon plans](https://neon.com/docs/introduction/plans), [Supabase pricing](https://supabase.com/pricing), [Supabase free-project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), and [Render free instance limits](https://render.com/docs/free).

## More time

After the reliability stretch, consider an archive schema/version marker and retention policy, PostgreSQL full-text search, document detail pages, richer agency filters, accessibility/keyboard polish, and a scheduled refresh. Hosting a seeded preview and making a walkthrough stays last; these are discussion points, not the 2–3 hour baseline.

## Submission checklist

- [ ] README covers requirements, setup/run steps, and what more time would change.
- [ ] Be ready to explain the identity/upsert rule, source pagination, retries, API cursor, and the main tradeoffs in a technical discussion. AI-assisted implementation is allowed by the brief.
- [ ] Before delivery, choose the submission path in the brief: grant GitHub access to `joshjbayne@gmail.com`, or send a zip to `josh.bayne@maiven.tech`.

## Reconnaissance notes

- The candidate brief is in [`Maiven_Takehome_Assessment.pdf`](/Users/steekam/sandbox/maiven-takehome/Maiven_Takehome_Assessment.pdf).
- The Federal Register docs confirm public endpoints require no API key: [API documentation](https://www.federalregister.gov/developers/documentation/api/v1).
- The 2026-09-24 OpenAPI snapshot is stored at [`pipelines/ingest/spec/federal-register.openapi.json`](../pipelines/ingest/spec/federal-register.openapi.json). It lists 14 GET paths, parameter/component schemas, and no successful response models.
- A live EPA Rules request confirmed the agency/type filters and result envelope. `next_page_url` preserves filters and contains `search_after_cursor`; `count`/`total_pages` disagreed with the requested page size. `per_page=1` returned 20 records, while `per_page=2` returned two.
- Two sample responses included an upstream `x-request-id` but no rate-limit headers. EPA-specific result fields and the `fields[]` projection are confirmed; server quota remains undocumented.
- The [JSON:API 1.1 spec](https://jsonapi.org/format/) defines the media type, resource envelope, error member, pagination links, and `page` parameter family. Plan to follow those rules for the documents collection endpoint.
