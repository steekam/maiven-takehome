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
- [ ] `GET /api/documents` returns JSON:API 1.1 collection documents with newest publication dates first, an inclusive publication-date filter, and case-insensitive text search.
- [ ] The API returns 20 documents per page and a JSON:API pagination link for the next 20.
- [ ] One page displays documents and wires up filters, search, and Load more.
- [ ] Tests cover text cleaning and ingest re-run behavior.
- [ ] README explains requirements, setup, how to run, and what more time would change.

## Deliverable invariants

1. `document_number` is the stable source identity and has a unique database constraint.
2. Ingest writes use an upsert inside a transaction; never clear the table before loading. A later run may update a known document without removing other rows.
3. Archive each fetched source page as a new Parquet file before transforming it. Keep raw document JSON available there; normalize serving fields into Postgres and never overwrite an older archive file.
4. The upstream run stops after 100 unique documents or a confirmed end of results. `count` and `total_pages` are informational only.
5. The serving API sorts by `(publication_date DESC, document_number DESC)` for deterministic ties. A changed search or date filter starts pagination over.
6. Network failures and malformed responses are visible as failed runs. Do not log and skip them as if ingest succeeded.
7. Runtime logs are append-only JSONL files under root `logs/`, ignored by Git. Keep payloads out of logs; use run/request IDs to connect log events to Parquet source pages.

## Proposed shape

```text
Federal Register API
        │ one sequential page request at a time
        ▼
Python CLI ── raw page ──> immutable Parquet archive
    │ clean + normalize
    └── psycopg parameterized SQL ──> PostgreSQL documents
                                          │
                             Next.js App Router + Drizzle
                             JSON:API GET (20 + cursor link)
                                          │
                                          ▼
                             list + filters + Load more

Python Loguru ──> logs/ingest.jsonl       Pino ──> logs/web.jsonl
                         (append-only, gitignored)
```

Keep the Postgres schema small: `documents` with `document_number`, `title`, `publication_date`, `effective_on`, `abstract`, `agencies` JSON, `html_url`, and timestamps if useful. The takehome does not need an ingestion job engine or a normalized agency catalog.

Write each source page atomically to `data/raw/federalregister/run_id=<id>/page-0001.parquet`. Use PyArrow to write columns for `run_id`, page number, fetch time, `document_number`, and the original document object serialized as `payload_json`. Archive the raw page before cleaning or upserting so a failed database write still leaves input to inspect or replay. Keep `data/raw/` separate from diagnostic logs.

Write structured events to `logs/ingest.jsonl` and `logs/web.jsonl`. Each line gets a timestamp, level, service, event name, and `run_id` or `request_id`, plus the relevant page, status, duration, count, retry delay, or error class. Never log the full source payload; the Parquet archive owns that detail.

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
    workflow.py            unique-document cap and ingest orchestration
    archive.py             atomic Parquet page snapshots
    normalize.py           raw document to serving row
    store.py               parameterized Postgres upsert
  tests/
    fixtures/
    test_client.py
    test_normalize.py
    test_workflow.py
compose.yaml              local PostgreSQL
data/raw/                 immutable Parquet source archive
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
| Raw source archive | Before normalization, write every successful result page to a unique Parquet path under `data/raw/federalregister/run_id=<id>/`. Store the original result object as `payload_json` plus page/run metadata. | Preserves inputs for replay and agent diagnosis if normalization or the DB write fails. Use an atomic temp-file rename; never replace an existing run/page file. |
| Runtime logs | Use Loguru in Python and Pino in the Next.js server for JSONL append sinks at `logs/ingest.jsonl` and `logs/web.jsonl`. Add `/logs/` to root `.gitignore`. | `pinio` interpreted as Pino. Keep human decisions in `docs/devlog.md`; logs hold machine events only. Do not log raw payloads. |
| API format | Follow JSON:API 1.1 for the supported read-only documents collection: `application/vnd.api+json`, top-level `data`, resource objects (`type: documents`, `id: document_number`, `attributes`), top-level `links.self`/`links.next`, and JSON:API `errors`. | Do not return a custom `{ items, nextCursor }` envelope. This is a scoped read API; writes, relationships, `include`, and compound documents are out of scope. Keep `agencies` as an attribute. |
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

Respond with `Content-Type: application/vnd.api+json` and handle `Accept` negotiation for the supported representation. The database query fetches 21 matches in the requested order. Return the first 20; use the extra row to decide whether `links.next` exists. The next URL carries the cursor from the final returned row, not the extra row, plus the active filters and sort. Return invalid-parameter failures with a top-level `errors` array and no `data` member. Keep the API spec-shaped within its read-only scope; do not claim support for unimplemented JSON:API operations.

## Execution plan

| Stage | Time | Work | Exit check |
| --- | ---: | --- | --- |
| 0. API contract | 10 min | Complete: save the OpenAPI snapshot, review endpoint/query schemas, and probe EPA Rules with a small page. Record that response bodies are undocumented, pagination uses `next_page_url`, and no quota headers were observed. | Request, response-envelope, and retry assumptions are recorded. |
| 1. Ingest tracer bullet | 40 min | Scaffold the uv project and configure the HTTP client. Get one representative EPA Rule through typed query → source page → raw Parquet → normalization → Postgres upsert. | One source page is archived and one row is upserted in local Postgres. |
| 2. Complete ingest path | 35 min | Add next-link iteration, the 100-unique-document cap, bounded retry classification, append-only page archives, and Loguru run events. | Two fixture runs leave row count stable and create new Parquet pages; failures include a run ID and error class. |
| 3. Serve and display | 55 min | Add the JSON:API collection/resource envelope, media negotiation, inclusive date filters, case-insensitive search, stable cursor ordering, pagination links/errors, Pino events, and the list UI. | API and UI support search, filters, and Load more; request events are correlated. |
| 4. Required checks and handoff | 30 min | Add focused tests, write README, run the full local path twice, review logs and git diff, and note known limits. | Required tests pass; README setup works from a clean local database; no unrelated files are committed. |

Total planned time: 170 minutes, leaving 10 minutes of the 3-hour ceiling for setup friction. Work starts with the ingestion client and its source contract. If time slips, keep the ingest path, idempotent writes, JSON:API collection contract, required tests, and README. Defer visual polish and hosting first.

## Verification and observability

- Keep one recorded, small EPA Rules probe for the actual `results` shape, agency shape, dates, ordering, pagination URL, status, and headers. Do not load-test a public API.
- Test request serialization with repeated `conditions[agencies][]`, `conditions[type][]`, and optional `fields[]` keys. Check date bounds and `per_page` against the OpenAPI limits; keep the observed `per_page=1` response anomaly in the client fixture.
- Use fixture pages to test `next_page_url` traversal, same-origin checking, unique `document_number` counting, the 100-document cap, and duplicate IDs across pages. Ignore `count`/`total_pages`.
- Test the retry classifier separately: transport timeout/connection failure, 408, 429 with delta/date `Retry-After`, 5xx, permanent 4xx, malformed JSON, and missing/invalid page envelope. Retries stay bounded and serial.
- Emit one structured run summary with `run_id`, pages fetched, unique documents seen, rows inserted/updated, retries, duration, final status, and failure class. Log each retry with status and delay. Avoid a durable run/job subsystem.
- Read each written Parquet page back and compare `document_number` and `payload_json` with the fixture. Confirm a later run creates a new path and leaves earlier files unchanged.
- Parse each JSONL line as JSON. Confirm a second run/request appends lines, each event has a correlation ID, and raw source fields stay in Parquet rather than logs.
- Test `clean_text` with whitespace and markup/entity examples that the implementation actually handles.
- Test re-run behavior against Postgres: ingest the same fixture twice, assert one row per `document_number`, and assert a previously stored unrelated row remains.
- Verify the route's media type negotiation and JSON:API structure with no filters, each filter alone, combined filters, invalid dates, and a second cursor page. Confirm `links.next` carries filters and no rows repeat across adjacent pages in a static fixture.
- Run the UI once with results, no results, loading, and API failure. Confirm it reads `data` and follows `links.next`; changing filters resets the list and current link.
- Record the exact verification command and result in the devlog for each completed stage.
- When handing a failure to an agent, include the command, run/request ID, JSONL file path, relevant event/error class, and a small log excerpt. Have the agent inspect those events and the matching Parquet page; do not paste entire source payloads into the log or prompt.

## Reuse from `pursuit-map`

Borrow the small ideas from [`http_client.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/http_client.py) and [`normalize.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/normalize.py): classify transient vs permanent errors, respect `Retry-After`, trim/collapse display text, and preserve raw values where useful. The bulk runner and supervisor are useful reference material, but adaptive concurrency probes, a circuit breaker, durable job leases, response archives, and a full provenance ledger exceed this assignment.

## Optional hosted preview

Keep the default demo local. If the app is complete and there is time for a public preview, Neon is a good first Postgres candidate: its current free plan lists 100 CU-hours per project/month and 0.5 GB storage, with compute scaling to zero after five idle minutes. That can add a cold start. Supabase also offers free Postgres with 500 MB, but its free projects pause after a week of inactivity. Render's free Postgres expires after 30 days, so it is a poor fit for a preview expected to remain available.

Check current limits before creating a hosted database: [Neon plans](https://neon.com/docs/introduction/plans), [Supabase pricing](https://supabase.com/pricing), [Supabase free-project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), and [Render free instance limits](https://render.com/docs/free).

## More time

Only after the required path works: add a Parquet schema/version marker and retention policy, add an ingestion-run table and resumable checkpoint, use PostgreSQL full-text search, support document detail pages and richer agency filters, add accessibility/keyboard polish, deploy the web app and database, and monitor a scheduled refresh. These are discussion points, not the 2–3 hour target.

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
