# Local database

The app and ingest script share the machine's local PostgreSQL database named `maiven-takehome`. Keep using the local PostgreSQL service already installed on the developer machine; no container runtime is needed for development.

Install PostgreSQL and make sure its local service is running. Create the database if it does not exist, running `createdb` as the local PostgreSQL role that will own it:

```sh
createdb maiven-takehome
cp .env.local.example .env.local
# Edit DATABASE_URL to use the local PostgreSQL role that owns this database.
pnpm install
pnpm db:migrate
```

If the database already exists, skip `createdb`. The example URL uses `your_local_role`; replace it with the PostgreSQL role that owns `maiven-takehome`, for example `postgresql://steekam@127.0.0.1:5432/maiven-takehome`. Varlock reads the committed `.env.schema` and ignored `.env.local`. `DATABASE_URL` is required and marked sensitive. Drizzle Kit commands run under `varlock run` so the validated value reaches the migration process.

Generate a migration after changing `apps/web/src/db/schema.ts`:

```sh
pnpm db:generate
pnpm db:migrate
```

`docker-compose.yaml` is an optional PostgreSQL service for reviewers who want a quick containerized setup. Its default host port is 5433 to avoid colliding with local PostgreSQL on 5432. Set `POSTGRES_PORT` to change it, then use `postgresql://maiven:maiven-dev@127.0.0.1:<port>/maiven-takehome` in `.env.local`. Compose is not part of the local development path.
