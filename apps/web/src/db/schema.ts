import { sql } from "drizzle-orm";
import {
  check,
  date,
  foreignKey,
  integer,
  jsonb,
  pgTable,
  primaryKey,
  text,
  timestamp,
  unique,
  uuid,
  index,
} from "drizzle-orm/pg-core";

export type Agency = Record<string, unknown>;
export type IngestRunStatus = "running" | "failed" | "succeeded";
export type IngestDocumentOutcome = "inserted" | "updated";

export const documents = pgTable(
  "documents",
  {
    documentNumber: text("document_number").primaryKey(),
    title: text("title").notNull(),
    publicationDate: date("publication_date", { mode: "string" }).notNull(),
    effectiveOn: date("effective_on", { mode: "string" }),
    abstract: text("abstract"),
    agencies: jsonb("agencies").$type<Agency[]>().notNull().default(sql`'[]'::jsonb`),
    htmlUrl: text("html_url").notNull(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => [
    index("documents_publication_cursor_idx").on(
      table.publicationDate.desc(),
      table.documentNumber.desc(),
    ),
  ],
);

export const ingestRuns = pgTable(
  "ingest_runs",
  {
    runId: uuid("run_id").primaryKey().defaultRandom(),
    status: text("status").$type<IngestRunStatus>().notNull().default("running"),
    queryFingerprint: text("query_fingerprint").notNull(),
    uniqueTarget: integer("unique_target").notNull().default(100),
    nextPageUrl: text("next_page_url"),
    pagesFetched: integer("pages_fetched").notNull().default(0),
    uniqueDocumentsSeen: integer("unique_documents_seen").notNull().default(0),
    insertedCount: integer("inserted_count").notNull().default(0),
    updatedCount: integer("updated_count").notNull().default(0),
    retries: integer("retries").notNull().default(0),
    failureClass: text("failure_class"),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
  },
  (table) => [
    check("ingest_runs_status_check", sql`${table.status} in ('running', 'failed', 'succeeded')`),
    check("ingest_runs_unique_target_check", sql`${table.uniqueTarget} > 0`),
    check(
      "ingest_runs_counters_check",
      sql`${table.pagesFetched} >= 0 and ${table.uniqueDocumentsSeen} >= 0 and ${table.insertedCount} >= 0 and ${table.updatedCount} >= 0 and ${table.retries} >= 0`,
    ),
  ],
);

export const ingestRunPages = pgTable(
  "ingest_run_pages",
  {
    requestId: uuid("request_id").primaryKey(),
    runId: uuid("run_id")
      .notNull()
      .references(() => ingestRuns.runId, { onDelete: "cascade" }),
    pageNumber: integer("page_number").notNull(),
    fetchedAt: timestamp("fetched_at", { withTimezone: true }).notNull(),
    httpStatus: integer("http_status").notNull(),
    upstreamRequestId: text("upstream_request_id"),
    archivePath: text("archive_path").notNull(),
    contentSha256: text("content_sha256").notNull(),
  },
  (table) => [
    unique("ingest_run_pages_run_request_unique").on(table.runId, table.requestId),
    unique("ingest_run_pages_run_page_unique").on(table.runId, table.pageNumber),
    check("ingest_run_pages_page_number_check", sql`${table.pageNumber} > 0`),
    check("ingest_run_pages_http_status_check", sql`${table.httpStatus} between 100 and 599`),
    check("ingest_run_pages_sha256_check", sql`${table.contentSha256} ~ '^[0-9a-f]{64}$'`),
  ],
);

export const ingestRunDocuments = pgTable(
  "ingest_run_documents",
  {
    runId: uuid("run_id").notNull(),
    requestId: uuid("request_id").notNull(),
    documentNumber: text("document_number")
      .notNull()
      .references(() => documents.documentNumber),
    outcome: text("outcome").$type<IngestDocumentOutcome>().notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.runId, table.documentNumber] }),
    foreignKey({
      columns: [table.runId, table.requestId],
      foreignColumns: [ingestRunPages.runId, ingestRunPages.requestId],
      name: "ingest_run_documents_page_fk",
    }).onDelete("cascade"),
    check("ingest_run_documents_outcome_check", sql`${table.outcome} in ('inserted', 'updated')`),
    index("ingest_run_documents_request_idx").on(table.requestId),
  ],
);
