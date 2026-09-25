# Federal Register ingest

Requires Python 3.11+, `uv`, the committed PostgreSQL migrations, and the root Varlock `.env.local` configuration.

From the repository root:

```sh
uv sync --project pipelines/ingest --extra dev
pnpm --filter @maiven/db exec varlock run -- uv run --project ../../pipelines/ingest federal-register-ingest
```

Apply all checked-in DB migrations before the first run:

```sh
pnpm db:migrate
```

The run defaults to 100 unique `document_number` values and requests 100 results per API page. Change the unique-document target independently with `--max-unique-documents`; change the upstream page size with `--per-page`. Add `--new-run` to start a separate run instead of resuming the latest incomplete one. Date filters are available to cover source searches wider than Federal Register's 2,000-result pagination limit.

## Run flow

```text
Federal Register metadata JSON
  → bounded HTTP fetch + retry
  → per-run evidence: raw responses + transport failures; fsync
  → normalize + fingerprint source payload
  → one DB transaction: latest document + metadata version + page/run checkpoint
  → API serves latest rows + ingest freshness
```

Run evidence lives under `data/raw/federalregister/run_id=<uuid>/`: `responses.jsonl` holds response bodies and hashes; `transport_failures.jsonl` holds attempts that received no complete response. The run summary joins that evidence with the PostgreSQL report. `logs/ingest.jsonl` remains diagnostics only.

`--max-unique-documents` is the target; `--per-page` controls page size. Run stops when it reaches the target, exhausts the source, or reaches the 2,000-result source ceiling. The first two end as `succeeded`; the ceiling ends as `partial` and CLI exits 2. A transform-version change changes the run fingerprint, so an older incomplete run needs `--new-run`; that option marks prior incomplete runs `superseded`. A single PostgreSQL advisory lock prevents concurrent ingest writers.

Responses larger than 32 MiB fail with a bounded archived prefix. `Retry-After` is capped at 60 seconds. Override with `FEDERAL_REGISTER_MAX_RESPONSE_BYTES` and `FEDERAL_REGISTER_RETRY_AFTER_MAX`.

## Assumptions and decisions

`documents` is the latest-state projection. On conflict, every mapped source field is replaced, including fields whose source value is `null`; omitted optional fields also normalize to `null`. Metadata snapshots preserve the original source JSON shape, so omitted and explicit-null fields remain distinguishable in version history. Review this null-clearing policy if consumers need “unknown” to differ from “cleared”.

Each distinct source metadata payload is retained in `document_versions`, keyed by document number and canonical JSON SHA-256. Run-document rows point to the source version observed on that page. Rule-body XML/HTML is not downloaded. Existing document rows gain a version the next time a run sees them; no historical archive backfill runs automatically. `updated_records` counts upserts to existing rows, including identical metadata; it does not mean every field changed.

Live runs verified first-snapshot creation and run-to-version links for 2,100 documents. They did not ingest any document twice. A controlled PostgreSQL integration case now checks that a changed source payload creates a distinct snapshot, updates the latest row, and links the new run to that snapshot. The live API history still has not shown an actual source change for a repeated document.

## Daily refresh

The repository includes `scripts/ingest-daily.sh`. It runs the default 100-unique-document ingest through Varlock. To schedule it, create the log directory and add a cron entry; cron uses the host's local timezone:

```sh
mkdir -p logs
crontab -e
```

Add a line with the absolute repository path (update `PATH` to include the locations returned by `command -v pnpm` and `command -v uv` in your shell):

```cron
PATH=/Users/you/.local/share/pnpm:/Users/you/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
15 2 * * * /Users/you/path/to/maiven-takehome/scripts/ingest-daily.sh >> /Users/you/path/to/maiven-takehome/logs/ingest-cron.log 2>&1
```

The script does not install or enable cron. Cron exits nonzero when a run fails or ends partial at the Federal Register 2,000-result pagination ceiling. The web API reports the last successful ingest and latest run state; the timestamp means an ingest completed, not that every historical record was revisited.

Run the focused suite from the repository root:

```sh
uv run --project pipelines/ingest --extra dev pytest pipelines/ingest/tests
```

The PostgreSQL integration test runs when `INGEST_TEST_DATABASE_URL` points to a disposable database with the committed migrations applied. It refuses a database name without `test`; `--new-run` semantics in the test can supersede incomplete runs, so never point it at the application database. It uses unique test document numbers and deletes only its own run and document rows.

Per-run response and transport-failure evidence append to the gitignored `data/raw/federalregister/run_id=<uuid>/` directory. Structured diagnostics append to `logs/ingest.jsonl`. The Python project uses Psycopg 3 parameterized SQL and does not manage migrations. Apply the checked-in Drizzle migrations first with `pnpm db:migrate`.
