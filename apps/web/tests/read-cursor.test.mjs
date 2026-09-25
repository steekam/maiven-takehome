import assert from "node:assert/strict";
import test from "node:test";
import { PgDialect } from "drizzle-orm/pg-core";
import { buildCursorCondition } from "../lib/documents/read.ts";

const dialect = new PgDialect();

function query({ sort, direction, value, documentNumber }) {
  return {
    q: "",
    dateFrom: null,
    dateTo: null,
    sort,
    direction,
    pageSize: 20,
    cursor: { field: sort, direction, value, documentNumber, filterKey: "[]" },
  };
}

test("builds an ascending keyset predicate with the descending document-number tie-breaker", () => {
  const condition = buildCursorCondition(query({
    sort: "title",
    direction: "asc",
    value: "Air rule",
    documentNumber: "2026-00010",
  }));
  const compiled = dialect.sqlToQuery(condition);

  assert.match(compiled.sql, /"title" > \$1/);
  assert.match(compiled.sql, /"title" = \$2/);
  assert.match(compiled.sql, /"document_number" < \$3/);
  assert.deepEqual(compiled.params, ["Air rule", "Air rule", "2026-00010"]);
});

test("builds a descending keyset predicate with the same deterministic tie-breaker", () => {
  const condition = buildCursorCondition(query({
    sort: "publication_date",
    direction: "desc",
    value: "2026-09-24",
    documentNumber: "2026-00010",
  }));
  const compiled = dialect.sqlToQuery(condition);

  assert.match(compiled.sql, /"publication_date" < \$1/);
  assert.match(compiled.sql, /"publication_date" = \$2/);
  assert.match(compiled.sql, /"document_number" < \$3/);
  assert.deepEqual(compiled.params, ["2026-09-24", "2026-09-24", "2026-00010"]);
});

test("uses only the unique document number for document-number pagination", () => {
  const condition = buildCursorCondition(query({
    sort: "document_number",
    direction: "asc",
    value: "2026-00010",
    documentNumber: "2026-00010",
  }));
  const compiled = dialect.sqlToQuery(condition);

  assert.match(compiled.sql, /"document_number" > \$1/);
  assert.deepEqual(compiled.params, ["2026-00010"]);
});

test("does not build a cursor predicate for the first page", () => {
  assert.equal(buildCursorCondition({
    q: "",
    dateFrom: null,
    dateTo: null,
    sort: "publication_date",
    direction: "desc",
    pageSize: 20,
    cursor: null,
  }), undefined);
});
