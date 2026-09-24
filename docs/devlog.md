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
