# Maiven takehome plan

**Status:** planning and reconnaissance  
**Updated:** 2026-09-24  
**Time box:** 2–3 hours, matching the candidate brief

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
pipelines/ingest/         uv project: client, normalization, CLI, PyArrow archive, tests
compose.yaml              local PostgreSQL
data/raw/                 immutable Parquet source archive
logs/                     local JSONL diagnostics; ignored by Git
docs/                     plan, append-only devlog, README links
```

Keep the two toolchains independent. Run migrations from the web app before ingesting; the Python CLI uses the same Postgres columns through parameterized SQL. Skip Turborepo or a cross-language task runner unless setup proves it necessary.

## Decisions and assumptions

| Topic | Plan | Reason / follow-up |
| --- | --- | --- |
| “A run should ingest 100 documents” | Treat 100 as a per-run target of unique documents, not a lifetime database cap. Stop earlier only when results are exhausted. | Put this in a README “Assumptions” section: “Each run fetches up to 100 distinct Federal Register documents. This is a per-run target, not a lifetime database cap or 100 new-to-database rows. Re-runs upsert matching documents, and existing rows are retained.” |
| Source pagination | Request 20 at a time, follow a server-provided next-page URL if present; otherwise increment `page`. Count unique document numbers. Stop at 100; below 100, continue until an empty result. | Does not need a total count. If response shape differs, settle it in the API probe before implementation. |
| Do we need an extra upstream page? | Only if fewer than 100 have been collected and the response does not provide a next-page link. An empty result confirms the end. Once 100 unique records are collected, stop. | Avoid trusting totals. No sixth request is needed just to prove the 100-document target was met. |
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
| Client behavior | Start with sequential page requests, bounded timeout, and at most three retries for timeouts, 408, 429, and 5xx. Respect `Retry-After`; fail fast on other 4xx and invalid payloads. | A 100-document run needs about five page requests. Concurrency adds little and risks needless source load. Record status, latency, retries, and terminal error class. |
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
| 0. Recon and scaffold | 10 min | Repo currently has the brief and planning docs only. Node 24.21, `uv` 0.10.6, Docker 29.4, and `psql` 17.7 are available. Probe one Federal Register response for field shape, ordering, next-page behavior, response headers, and practical request size. If this shell still cannot resolve the API, use a recorded fixture for local work and retry the probe from a network-enabled environment. | API assumptions are recorded; app and database start locally. |
| 1. Tracer bullet | 40 min | Get one representative document through raw Parquet → normalize → Postgres → JSON:API → rendered list row. Add one migration and one seed/ingest path. | One source record is archived and visible from the app against local Postgres. |
| 2. Complete ingest path | 35 min | Add 100-unique-document paging, append-only page archives, upsert, bounded retry classification, and Loguru run events. | Two consecutive runs leave row count stable and create new Parquet pages; failures include a run ID and error class. |
| 3. Serve contract | 40 min | Add the JSON:API collection/resource envelope, media type, inclusive date filters, case-insensitive search, stable cursor ordering, pagination links, JSON:API errors, and Pino request events. | API returns valid JSON:API responses and appends correlated request events for unfiltered, filtered, invalid-date, and next-page requests. |
| 4. Display | 15 min | Wire search, date inputs, result list, empty/loading/error states, and Load more. Reset accumulated rows/cursor when filters change. | A reviewer can search, filter, and fetch another page without refreshing. |
| 5. Required checks and handoff | 30 min | Add the two focused tests, write README, run the full local path twice, review logs and git diff, note known limits. | Required tests pass; README setup works from a clean local database; no unrelated files are committed. |

Total planned time: 170 minutes, leaving 10 minutes of the 3-hour ceiling for setup friction. If time slips, keep the tracer bullet, idempotent ingest, JSON:API collection contract, required tests, and README. Defer visual polish and hosting first.

## Verification and observability

- Probe the source with a single small request; inspect the actual `results` shape, agency shape, dates, ordering, pagination link/fields, status, and headers. Do not load-test a public API.
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
- The [JSON:API 1.1 spec](https://jsonapi.org/format/) defines the media type, resource envelope, error member, pagination links, and `page` parameter family. Plan to follow those rules for the documents collection endpoint.
- The first live `curl` attempt from this workspace failed at DNS resolution, so rate-limit headers and the response's next-page shape remain unverified here. Repeat stage 0 from a network-enabled shell before locking the client implementation.
