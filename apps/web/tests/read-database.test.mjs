import assert from "node:assert/strict";
import test from "node:test";
import { PgDialect } from "drizzle-orm/pg-core";
import { readDocuments, readIngestFreshness } from "../lib/documents/read.ts";
import { configureDatabaseResults, getDatabaseCalls } from "./stubs/database.mjs";

const dialect = new PgDialect();

function documentQuery(overrides = {}) {
  return {
    q: "",
    dateFrom: null,
    dateTo: null,
    sort: "publication_date",
    direction: "desc",
    pageSize: 20,
    cursor: null,
    ...overrides,
  };
}

function makeRow(overrides = {}) {
  return {
    documentNumber: "2026-00001",
    title: "EPA rule fixture",
    type: "Rule",
    publicationDate: "2026-09-24",
    effectiveOn: null,
    signingDate: null,
    commentsCloseOn: null,
    abstract: "A test rule.",
    action: null,
    agencyNames: ["Environmental Protection Agency"],
    citation: "91 FR 1000",
    docketIds: null,
    cfrReferences: null,
    htmlUrl: null,
    publicInspectionPdfUrl: null,
    pdfUrl: null,
    sortValue: "EPA rule fixture",
    ...overrides,
  };
}

test("readDocuments builds full-text/date SQL and maps rows into a cursor page", async () => {
  configureDatabaseResults([
    makeRow({
      publicInspectionPdfUrl: "https://example.test/public.pdf",
      pdfUrl: "https://example.test/official.pdf",
      sortValue: "environmental protection agency",
    }),
    makeRow({ documentNumber: "2026-00002", sortValue: "environmental protection agency" }),
  ]);

  const query = documentQuery({
    q: "air OR ozone",
    dateFrom: "2026-09-01",
    dateTo: "2026-09-30",
    sort: "agency",
    direction: "asc",
    pageSize: 1,
  });
  const page = await readDocuments(query);

  assert.equal(page.rows.length, 1);
  assert.equal(page.rows[0].documentNumber, "2026-00001");
  assert.equal(page.rows[0].pdfUrl, "https://example.test/public.pdf");
  assert.equal("sortValue" in page.rows[0], false);
  assert.equal(page.hasMore, true);

  const cursor = JSON.parse(Buffer.from(page.nextCursor, "base64url").toString("utf8"));
  assert.deepEqual(cursor, {
    field: "agency",
    direction: "asc",
    value: "environmental protection agency",
    documentNumber: "2026-00001",
    filterKey: JSON.stringify(["air OR ozone", "2026-09-01", "2026-09-30"]),
  });

  const [call] = getDatabaseCalls();
  const where = dialect.sqlToQuery(call.condition);
  assert.match(where.sql, /to_tsvector\('english'/);
  assert.match(where.sql, /websearch_to_tsquery\('english'/);
  assert.match(where.sql, /"publication_date" >=/);
  assert.match(where.sql, /"publication_date" <=/);
  assert.deepEqual(where.params, ["air OR ozone", "2026-09-01", "2026-09-30"]);
  assert.equal(call.limit, 2);
  assert.equal(call.order.length, 2);
  assert.match(dialect.sqlToQuery(call.order[1]).sql, /"document_number" desc/);
});

test("readDocuments returns empty pages without a next cursor", async () => {
  configureDatabaseResults([]);

  const page = await readDocuments(documentQuery());

  assert.deepEqual(page, { rows: [], hasMore: false, nextCursor: null });
  assert.equal(getDatabaseCalls()[0].condition, undefined);
});

test("readIngestFreshness reports the last success and latest run", async () => {
  configureDatabaseResults(
    [{ finishedAt: new Date("2026-09-24T09:15:00.000Z") }],
    [{
      status: "running",
      completionReason: null,
      startedAt: new Date("2026-09-25T10:00:00.000Z"),
      finishedAt: null,
    }],
  );

  assert.deepEqual(await readIngestFreshness(), {
    last_successful_at: "2026-09-24T09:15:00.000Z",
    latest_run: {
      status: "running",
      completion_reason: null,
      started_at: "2026-09-25T10:00:00.000Z",
      finished_at: null,
    },
  });
  assert.equal(getDatabaseCalls().length, 2);
});

test("readIngestFreshness handles an empty ingestion history", async () => {
  configureDatabaseResults([], []);

  assert.deepEqual(await readIngestFreshness(), {
    last_successful_at: null,
    latest_run: null,
  });
});
