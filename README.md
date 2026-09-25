# Maiven takehome

Search public Federal Register documents in a read-only web interface.

For web app setup, request flow, and checks, see the [web README](apps/web/README.md).

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

The web dev, build, and start scripts load configuration through Varlock. Telemetry stays off until `OTEL_EXPORTER_OTLP_ENDPOINT` is set; add the local value from `.env.local.example` to `.env.local` to enable it.

## Local telemetry

Start the observability stack:

```sh
docker compose up -d otel-collector loki tempo prometheus grafana
```

Open Grafana at [http://127.0.0.1:3001](http://127.0.0.1:3001) and sign in with `admin` / `admin` on first launch. Prometheus, Loki, and Tempo are provisioned as data sources. Direct local endpoints are [Prometheus](http://127.0.0.1:9090), [Loki](http://127.0.0.1:3100), and [Tempo](http://127.0.0.1:3200).

The Next.js server sends traces and metrics to the OTLP Collector. Pino sends structured server logs to the collector, which routes traces to Tempo, logs to Loki, and metrics to Prometheus. In Grafana Explore, query errors with `{service_name="maiven-web"} | event="documents_query_failed"`. Open a log’s **Trace ID** link to view its trace; from a Tempo span, use **Logs for this span** to return to Loki. Query request counts with `maiven_api_requests_total`.

Stop the observability services with `docker compose stop otel-collector loki tempo prometheus grafana`.

The first slice traces `GET /api/documents`, PostgreSQL document searches, and ingest freshness reads. It records request counts and durations plus database operation counts and durations. The handled database-error event includes the API request ID and active trace/span IDs. Search terms and document content stay out of telemetry attributes.

To inspect normal traffic, load the library, then use Grafana Explore to search Tempo for `maiven-web` traces or Prometheus for `maiven_api_requests_total` and `maiven_db_operations_total`. Duration histograms are available as `maiven_api_request_duration_milliseconds_bucket` and `maiven_db_operation_duration_milliseconds_bucket`.

For a database failure drill, run a second web process with an unused PostgreSQL port, then request its API:

Terminal 1:

```sh
env DATABASE_URL=postgresql://maiven:maiven-dev@127.0.0.1:1/maiven-takehome \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 \
  PORT=3006 pnpm --filter @maiven/web dev
```

Terminal 2:

```sh
curl -H 'Accept: application/vnd.api+json' http://127.0.0.1:3006/api/documents
```

The request returns 503. In Grafana Explore, find the Pino event in Loki and follow its **Trace ID** link to the failed database child span in Tempo. The `DATABASE_UNAVAILABLE` response and `maiven_api_requests_total{status_class="5xx"}` series confirm the API outcome.

The ingest pipeline can be run separately; see [the ingest README](pipelines/ingest/README.md).
The web interface displays the last successful ingest time. For a daily cron setup, see the ingest README.

## Documents API

`GET /api/documents` returns a JSON:API 1.1 collection. It supports PostgreSQL English full-text search across titles and abstracts, inclusive publication date bounds, sorting by publication date/document number/title/type/agency, and cursor pagination. Search uses `websearch_to_tsquery`, with a matching GIN index. The page size defaults to 20 and is capped at 20.

```text
/api/documents?filter[q]=water&filter[publication_date][gte]=2026-01-01&sort=-publication_date&page[size]=20
```

The web page keeps search, date bounds, and sorting in the URL. TanStack Query follows the API's `links.next` for Load more. The PDF action prefers the public inspection PDF URI and falls back to the public PDF URI.

An explicit `sort=field` is ascending; prefix a field with `-` for descending (`sort=-field`). With no `sort` parameter, publication date defaults to descending so the latest rules appear first.

### Accept header

The endpoint returns only `application/vnd.api+json`. The `Accept` header can list media types separated by commas, with parameters separated by semicolons. The parser respects quoted values, so commas or semicolons inside quotes are part of a value, not separators.

It accepts an exact JSON:API type, `application/*`, or `*/*`. A `q` quality value from 0 to 1 controls whether a match is acceptable; `q=0` excludes it. The most specific matching range takes precedence, so `application/vnd.api+json;q=0` rejects JSON:API even if `*/*` is acceptable. This endpoint also rejects non-empty `ext` or `profile` parameters on the exact JSON:API type because it does not support those features. If no supported match remains, the route returns `406 Not Acceptable`. The parser is in [`accept.ts`](apps/web/lib/documents/accept.ts).

## Checks

```sh
pnpm --filter @maiven/web typecheck
pnpm --filter @maiven/web test:query
pnpm --filter @maiven/web exec next build --webpack
```

## More time

Add a schema-driven query descriptor that validates filter/sort/field-selection attributes at runtime and supports JSON:API sparse fieldsets. Add restoration of all pages loaded before refresh if users need deep result position preserved. Consider document detail pages, additional agency filters, accessibility polish, and a one-time archive backfill if existing records need version history.
