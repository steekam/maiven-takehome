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
3. Keep raw agency data available. Normalize display text and dates predictably; leave a missing or invalid optional date null rather than inventing one.
4. The upstream run stops after 100 unique documents or a confirmed end of results. `count` and `total_pages` are informational only.
5. The serving API sorts by `(publication_date DESC, document_number DESC)` for deterministic ties. A changed search or date filter starts pagination over.
6. Network failures and malformed responses are visible as failed runs. Do not log and skip them as if ingest succeeded.

## Proposed shape

```text
Federal Register API
        │ one sequential page request at a time
        ▼
Python CLI ── clean + normalize ── psycopg parameterized SQL
                                      │ upsert by document_number
                                      ▼
                              PostgreSQL documents
                                      │
                         Next.js App Router + Drizzle
                         GET /api/documents (20 + cursor)
                                      │
                                      ▼
                         one-page list + filters + Load more
```

Keep the shared schema small: `documents` with `document_number`, `title`, `publication_date`, `effective_on`, `abstract`, `agencies` JSON, `html_url`, and timestamps if useful. The takehome does not need an ingestion job engine or a normalized agency catalog.

### Repo shape

```text
apps/web/                 Next.js App Router: API, page, Drizzle schema/migrations
pipelines/ingest/         uv project: Federal Register client, normalization, CLI, tests
compose.yaml              local PostgreSQL
docs/                     plan, append-only devlog, README links
```

Keep the two toolchains independent. Run migrations from the web app before ingesting; the Python CLI uses the same Postgres columns through parameterized SQL. Skip Turborepo or a cross-language task runner unless setup proves it necessary.

## Decisions and assumptions

| Topic | Plan | Reason / follow-up |
| --- | --- | --- |
| “A run should ingest 100 documents” | Treat 100 as a per-run target of unique documents, not a lifetime database cap. Stop earlier only when results are exhausted. | This fits “recent” and allows later runs to keep refreshing/upserting recent records. Say this assumption in README. |
| Source pagination | Request 20 at a time, follow a server-provided next-page URL if present; otherwise increment `page`. Count unique document numbers. Stop at 100; below 100, continue until an empty result. | Does not need a total count. If response shape differs, settle it in the API probe before implementation. |
| Do we need an extra upstream page? | Only if fewer than 100 have been collected and the response does not provide a next-page link. An empty result confirms the end. Once 100 unique records are collected, stop. | Avoid trusting totals. No sixth request is needed just to prove the 100-document target was met. |
| API format | Target JSON:API 1.1 for the read-only documents collection: `application/vnd.api+json`, `data` resources (`type: documents`, `id: document_number`), `attributes`, `links.self`, `links.next`, and JSON:API `errors`. | This endpoint needs only collection reads. No writes, relationships, `include`, or compound documents. Keep `agencies` as an attribute. |
| Media negotiation | Return `Content-Type: application/vnd.api+json`; accept that media type and `*/*`, and return 406 when the client excludes it. | Keep response bodies in the JSON:API media type. No extension or profile support needed. |
| Filters and pages | Use `filter[publication_date][gte]`, `filter[publication_date][lte]`, `filter[q]`, `page[size]`, and `page[cursor]`. Default `sort=-publication_date,-document_number`. | JSON:API reserves these query parameter families. Filter meaning remains specific to this API. Enforce a maximum page size of 20. |
| “Fetch the next 20” | Use keyset/cursor pagination and expose the next request as `links.next`. Query 21 rows; set `links.next` only when row 21 exists, otherwise set it to null. | Cursor is the retrieval strategy; `links.next` is JSON:API's pagination link. No `COUNT(*)` or total needed. |
| Cursor sort key | Encode the last visible `(publication_date, document_number)` pair in `page[cursor]`. Carry the same filters and sort in the next link. | Unique, stable ordering handles ties and avoids offset shifts when new documents arrive. |
| Text cleaning and search | Trim and collapse whitespace in title/abstract; preserve agency objects as JSON. Search title and abstract with case-insensitive `ILIKE`. | Simple, visible normalization and search; enough for roughly 100 rows. |
| Date filter | Inclusive `filter[publication_date][gte]` and `filter[publication_date][lte]` on `publication_date`; reject invalid dates or lower bound after upper bound with 400. | JSON:API query family; no timezone conversion for date-only fields. |
| Database access | Python uses `psycopg` 3 with parameterized SQL, no Python ORM. TypeScript uses Drizzle for schema/migrations and typed queries. | Kysely is TypeScript-side. SQLAlchemy Core is the Python query-construction analogue without using its ORM layer; direct Psycopg SQL is leaner for this small fixed ingest. See [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/) and [Psycopg parameters](https://www.psycopg.org/psycopg3/docs/basic/params.html). |
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
        "document_number": "2026-12345",
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

Respond with `Content-Type: application/vnd.api+json` and handle `Accept` negotiation for that media type. The database query fetches 21 matches in the requested order. Return the first 20; use the extra row to decide whether `links.next` exists. The next URL carries the cursor from the final returned row, not the extra row, plus the active filters and sort. Return invalid-parameter failures with a top-level `errors` array and no `data` member.

## Execution plan

| Stage | Time | Work | Exit check |
| --- | ---: | --- | --- |
| 0. Recon and scaffold | 10 min | Repo currently has the brief and planning docs only. Node 24.21, `uv` 0.10.6, Docker 29.4, and `psql` 17.7 are available. Probe one Federal Register response for field shape, ordering, next-page behavior, response headers, and practical request size. If this shell still cannot resolve the API, use a recorded fixture for local work and retry the probe from a network-enabled environment. | API assumptions are recorded; app and database start locally. |
| 1. Tracer bullet | 45 min | Get one representative document through normalize → Postgres → API → rendered list row. Add one migration and one seed/ingest path. | One row is visible from the app against local Postgres. |
| 2. Complete ingest path | 30 min | Add 100-unique-document paging, upsert, bounded retry classification, and run summary logs. | Two consecutive runs leave row count stable for the same source window; a failure is visible and classified. |
| 3. Serve contract | 35 min | Add the JSON:API collection/resource envelope, media type, inclusive date filters, case-insensitive search, stable cursor ordering, pagination links, and JSON:API error objects. | API returns valid JSON:API responses for unfiltered, filtered, invalid-date, and next-page requests. |
| 4. Display | 20 min | Wire search, date inputs, result list, empty/loading/error states, and Load more. Reset accumulated rows/cursor when filters change. | A reviewer can search, filter, and fetch another page without refreshing. |
| 5. Required checks and handoff | 30 min | Add the two focused tests, write README, run the full local path twice, review logs and git diff, note known limits. | Required tests pass; README setup works from a clean local database; no unrelated files are committed. |

Total planned time: 170 minutes, leaving 10 minutes of the 3-hour ceiling for setup friction. If time slips, keep the tracer bullet, idempotent ingest, JSON:API collection contract, required tests, and README. Defer visual polish and hosting first.

## Verification and observability

- Probe the source with a single small request; inspect the actual `results` shape, agency shape, dates, ordering, pagination link/fields, status, and headers. Do not load-test a public API.
- Emit one structured run summary with `run_id`, pages fetched, unique documents seen, rows inserted/updated, retries, duration, final status, and failure class. Log each retry with status and delay. Avoid a durable run/job subsystem.
- Test `clean_text` with whitespace and markup/entity examples that the implementation actually handles.
- Test re-run behavior against Postgres: ingest the same fixture twice, assert one row per `document_number`, and assert a previously stored unrelated row remains.
- Verify the route's media type and JSON:API structure with no filters, each filter alone, combined filters, invalid dates, and a second cursor page. Confirm `links.next` carries filters and no rows repeat across adjacent pages in a static fixture.
- Run the UI once with results, no results, loading, and API failure. Confirm it reads `data` and follows `links.next`; changing filters resets the list and current link.
- Record the exact verification command and result in the devlog for each completed stage.

## Reuse from `pursuit-map`

Borrow the small ideas from [`http_client.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/http_client.py) and [`normalize.py`](/Users/steekam/Projects/pursuit-map/pipeline/src/pursuitmap/normalize.py): classify transient vs permanent errors, respect `Retry-After`, trim/collapse display text, and preserve raw values where useful. The bulk runner and supervisor are useful reference material, but adaptive concurrency probes, a circuit breaker, durable job leases, response archives, and a full provenance ledger exceed this assignment.

## Optional hosted preview

Keep the default demo local. If the app is complete and there is time for a public preview, Neon is a good first Postgres candidate: its current free plan lists 100 CU-hours per project/month and 0.5 GB storage, with compute scaling to zero after five idle minutes. That can add a cold start. Supabase also offers free Postgres with 500 MB, but its free projects pause after a week of inactivity. Render's free Postgres expires after 30 days, so it is a poor fit for a preview expected to remain available.

Check current limits before creating a hosted database: [Neon plans](https://neon.com/docs/introduction/plans), [Supabase pricing](https://supabase.com/pricing), [Supabase free-project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), and [Render free instance limits](https://render.com/docs/free).

## More time

Only after the required path works: retain raw source payloads with a schema/version marker, add an ingestion-run table and resumable checkpoint, use PostgreSQL full-text search, support document detail pages and richer agency filters, add accessibility/keyboard polish, deploy the web app and database, and monitor a scheduled refresh. These are discussion points, not the 2–3 hour target.

## Submission checklist

- [ ] README covers requirements, setup/run steps, and what more time would change.
- [ ] Be ready to explain the identity/upsert rule, source pagination, retries, API cursor, and the main tradeoffs in a technical discussion. AI-assisted implementation is allowed by the brief.
- [ ] Before delivery, choose the submission path in the brief: grant GitHub access to `joshjbayne@gmail.com`, or send a zip to `josh.bayne@maiven.tech`.

## Reconnaissance notes

- The candidate brief is in [`Maiven_Takehome_Assessment.pdf`](/Users/steekam/sandbox/maiven-takehome/Maiven_Takehome_Assessment.pdf).
- The Federal Register docs confirm public endpoints require no API key: [API documentation](https://www.federalregister.gov/developers/documentation/api/v1).
- The [JSON:API 1.1 spec](https://jsonapi.org/format/) defines the media type, resource envelope, error member, pagination links, and `page` parameter family. Plan to follow those rules for the documents collection endpoint.
- The first live `curl` attempt from this workspace failed at DNS resolution, so rate-limit headers and the response's next-page shape remain unverified here. Repeat stage 0 from a network-enabled shell before locking the client implementation.
