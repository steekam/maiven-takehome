# Maiven takehome

Search public Federal Register documents in a read-only web interface.

## Run locally

1. Install Node.js 24, pnpm 10, and PostgreSQL 17.
2. Create the `maiven-takehome` database and configure `DATABASE_URL` as described in [database setup](docs/database.md).
3. Install workspace dependencies and apply the Drizzle migration:

   ```sh
   pnpm install
   pnpm db:migrate
   ```

4. Start the web app:

   ```sh
   pnpm --filter @maiven/web dev
   ```

The web dev, build, and start scripts load `DATABASE_URL` through Varlock from the workspace's `.env.local`.

The ingest pipeline can be run separately; see [the ingest README](pipelines/ingest/README.md).
The web interface displays the last successful ingest time. For a daily cron setup, see the ingest README.

## Documents API

`GET /api/documents` returns a JSON:API 1.1 collection. It supports PostgreSQL English full-text search across titles and abstracts, inclusive publication date bounds, sorting by publication date/document number/title/type/agency, and cursor pagination. Search uses `websearch_to_tsquery`, with a matching GIN index. The page size defaults to 20 and is capped at 20.

```text
/api/documents?filter[q]=water&filter[publication_date][gte]=2026-01-01&sort=-publication_date&page[size]=20
```

The web page keeps search, date bounds, and sorting in the URL. TanStack Query follows the API's `links.next` for Load more. The PDF action prefers the public inspection PDF URI and falls back to the public PDF URI.

## Checks

```sh
pnpm --filter @maiven/web typecheck
pnpm --filter @maiven/web test:query
pnpm --filter @maiven/web exec next build --webpack
```

## More time

Add a schema-driven query descriptor that validates filter/sort/field-selection attributes at runtime and supports JSON:API sparse fieldsets. Add restoration of all pages loaded before refresh if users need deep result position preserved. Consider document detail pages, additional agency filters, accessibility polish, and a one-time archive backfill if existing records need version history.
