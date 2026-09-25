# Federal Register ingest

The Python pipeline fetches EPA rules from the Federal Register, normalizes
their metadata, and stores them in PostgreSQL. It does not download rule HTML or
PDF content.

For the shortest end-to-end setup, use the root
[Docker reviewer flow](../../README.md#run-the-assessment).

## Run locally

Requirements:

- Python 3.11 or later and `uv`
- Node.js and pnpm for database migrations
- PostgreSQL with `DATABASE_URL` set in the root `.env.local`
- Internet access to the Federal Register API

From the repository root:

```sh
pnpm db:migrate
uv sync --project pipelines/ingest --extra dev
./scripts/ingest.sh
```

The default run targets 100 unique document numbers and requests 100 results per
source page. It prints a JSON summary.

To ingest through the Compose stack after bootstrap, run:

```sh
./scripts/bootstrap-compose.sh ingest --max-unique-documents 100
```

## Choose the run scope

```text
./scripts/ingest.sh [--max-unique-documents N] [--per-page N]
  [--publication-date-gte YYYY-MM-DD]
  [--publication-date-lte YYYY-MM-DD] [--new-run]
```

- `--max-unique-documents` sets the distinct document target. Default: `100`.
- `--per-page` sets the Federal Register page size from 1 to 1000. Default:
  `100`.
- Publication-date options bound the source query inclusively.
- `--new-run` replaces an incompatible incomplete run instead of resuming it.

The source limits a search to 2,000 records. A run that reaches this limit
before its target exits `2` with status `partial`. Use date ranges for larger
backfills. Success exits `0`; failure exits `1`.

## Reliability model

The pipeline handles the brief's unreliable `count` and `total_pages` fields by
following the API's opaque `next_page_url` until it reaches the unique-document
target or the source ends.

Each page follows this sequence:

```text
Fetch -> archive response -> validate and normalize -> atomic PostgreSQL commit
```

The page transaction upserts the latest document, stores a version snapshot,
records run outcomes, and advances the checkpoint together. Rerunning does not
duplicate document rows. A matching incomplete run resumes from its committed
checkpoint. A PostgreSQL advisory lock prevents concurrent ingest writers.

Response evidence is stored under
`data/raw/federalregister/run_id=RUN_ID/`; structured diagnostics append to
`logs/ingest.jsonl`. Compose uses named volumes for both paths.

## Main code paths

| Path | Responsibility |
| --- | --- |
| `src/maiven_ingest/cli.py` | CLI arguments, settings, and exit codes. |
| `src/maiven_ingest/federal_register/client.py` | Requests, pagination, retries, and response validation. |
| `src/maiven_ingest/document_contract.py` | Source validation and normalization. |
| `src/maiven_ingest/workflow.py` | EPA query, page loop, resume, and run summary. |
| `src/maiven_ingest/db.py` | Advisory lock and atomic PostgreSQL persistence. |
| `src/maiven_ingest/archive.py` | Response and transport-failure evidence. |

## Run tests

```sh
uv run --project pipelines/ingest --extra dev pytest pipelines/ingest/tests
```

Unit tests cover text cleaning, Federal Register client behavior, paging,
retries, normalization, and workflow outcomes. PostgreSQL integration tests run
only when
`INGEST_TEST_DATABASE_URL` points to a migrated disposable database whose name
contains `test`. They cover rerun upserts, version links, locking, and page
transactions.

## Trade-offs

- Sequential requests preserve source order and simplify checkpoint recovery.
- Metadata versions preserve observed source changes, but existing rows gain
  history only when a later ingest sees them.
- The global advisory lock serializes every ingest query and holds one database
  connection for the run.
- `updated_records` counts upserts to existing rows; it does not prove a field
  changed.
