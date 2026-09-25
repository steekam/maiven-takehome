# Web app and API

The Next.js app serves and displays EPA rules stored by the ingest pipeline.
This guide covers native development; use the root
[Docker reviewer flow](../../README.md#run-the-assessment) for the shortest setup.

## Start locally

Requirements:

- Node.js 24 and pnpm 10.15.1
- PostgreSQL 17
- Python 3.11 or later and `uv` when the database needs ingest data

From the repository root:

1. Create the database and local configuration:

   ```sh
   createdb maiven-takehome
   cp .env.local.example .env.local
   ```

   Skip `createdb` if the database exists. Set `DATABASE_URL` in `.env.local` to
   the PostgreSQL role that owns it. See [database setup](../../docs/database.md).
   Remove `OTEL_EXPORTER_OTLP_ENDPOINT` unless the local collector is running.

2. Install dependencies and apply migrations:

   ```sh
   pnpm install
   pnpm db:migrate
   ```

3. If the database is empty, ingest documents:

   ```sh
   uv sync --project pipelines/ingest
   ./scripts/ingest.sh --max-unique-documents 100
   ```

4. Start Next.js:

   ```sh
   pnpm --filter @maiven/web dev
   ```

Open [http://localhost:3000](http://localhost:3000).

## Verify the app

```sh
curl -fsS http://localhost:3000/api/health
curl -fsS -H 'Accept: application/vnd.api+json' \
  http://localhost:3000/api/documents
```

The documents response contains a `data` array and a `links.next` URL when
another page exists.

## API contract

`GET /api/documents` returns JSON:API 1.1 with media type
`application/vnd.api+json`. It accepts these query parameters:

| Parameter | Meaning |
| --- | --- |
| `filter[q]` | Full-text search across title and abstract; maximum 200 characters. |
| `filter[publication_date][gte]` | Inclusive start date in `YYYY-MM-DD` format. |
| `filter[publication_date][lte]` | Inclusive end date in `YYYY-MM-DD` format. |
| `sort` | `publication_date`, `document_number`, `title`, `type`, or `agency`; prefix with `-` for descending. Default: `-publication_date`. |
| `page[size]` | One to 20 documents; default: 20. |
| `page[cursor]` | Opaque cursor from the previous response's `links.next`. |

Example:

```text
/api/documents?filter[q]=water&filter[publication_date][gte]=2026-01-01&sort=-publication_date&page[size]=20
```

The browser stores search, date, and sort state in the URL. TanStack Query
follows `links.next` for **Load More**. Selecting a row opens a detail panel; the
PDF action prefers the public inspection PDF, then the public PDF.

## Request flow

```text
Browser URL state -> Next.js route -> Zod validation -> Drizzle -> PostgreSQL
                  <- JSON:API page and cursor <-
```

Main code paths:

| Path | Responsibility |
| --- | --- |
| `components/document-library/` | Search, filters, results, detail panel, and query state. |
| `app/api/documents/route.ts` | Media negotiation, validation, and response mapping. |
| `lib/documents/query.ts` | Query schemas and cursor encoding. |
| `lib/documents/read.ts` | Search, filtering, sorting, pagination, and freshness queries. |
| `lib/documents/schemas.ts` | API response schemas. |
| `instrumentation.ts` | OpenTelemetry registration. |

## Run checks

```sh
pnpm --filter @maiven/web typecheck
pnpm --filter @maiven/web test
pnpm --filter @maiven/web test:coverage
pnpm --filter @maiven/web build
```

For ingest behavior and recovery, see the [ingest guide](../../pipelines/ingest/README.md).
