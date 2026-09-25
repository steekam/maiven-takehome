import assert from "node:assert/strict";
import test from "node:test";
import { acceptsJsonApi } from "../lib/documents/accept.ts";
import { documentFilterKey, encodeCursor, parseDocumentQuery } from "../lib/documents/query.ts";

test("accepts JSON:API and wildcards while rejecting unsupported media types and extensions", () => {
  assert.equal(acceptsJsonApi(null), true);
  assert.equal(acceptsJsonApi("application/vnd.api+json"), true);
  assert.equal(acceptsJsonApi("*/*"), true);
  assert.equal(acceptsJsonApi("text/html"), false);
  assert.equal(acceptsJsonApi("application/vnd.api+json;q=0"), false);
  assert.equal(acceptsJsonApi('application/vnd.api+json;ext="https://example.com/ext"'), false);
  assert.equal(acceptsJsonApi('application/vnd.api+json;profile="https://example.com/profile"'), false);
});

test("uses newest publication date and 20 rows by default", () => {
  const parsed = parseDocumentQuery(new URLSearchParams());
  assert.equal(parsed.ok, true);
  assert.equal(parsed.query.sort, "publication_date");
  assert.equal(parsed.query.direction, "desc");
  assert.equal(parsed.query.pageSize, 20);
});

test("accepts the agreed filters, page size, and agency sort", () => {
  const params = new URLSearchParams({
    "filter[q]": "clean air",
    "filter[publication_date][gte]": "2026-01-01",
    "filter[publication_date][lte]": "2026-01-31",
    "page[size]": "10",
    sort: "agency",
  });
  const parsed = parseDocumentQuery(params);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.query.q, "clean air");
  assert.equal(parsed.query.dateFrom, "2026-01-01");
  assert.equal(parsed.query.dateTo, "2026-01-31");
  assert.equal(parsed.query.sort, "agency");
  assert.equal(parsed.query.direction, "asc");
  assert.equal(parsed.query.pageSize, 10);
});

test("rejects invalid dates, reversed ranges, sort fields, and page sizes", () => {
  assert.equal(parseDocumentQuery(new URLSearchParams({ "filter[publication_date][gte]": "2026-02-30" })).ok, false);
  assert.equal(parseDocumentQuery(new URLSearchParams({ "filter[publication_date][gte]": "2026-02-02", "filter[publication_date][lte]": "2026-02-01" })).ok, false);
  assert.equal(parseDocumentQuery(new URLSearchParams({ sort: "updated_at" })).ok, false);
  assert.equal(parseDocumentQuery(new URLSearchParams({ "page[size]": "21" })).ok, false);
  const unsupportedFilter = parseDocumentQuery(new URLSearchParams({ "filter[effective_on]": "2026-01-01" }));
  assert.equal(unsupportedFilter.ok, false);
  assert.equal(unsupportedFilter.parameter, "filter[effective_on]");
});

test("rejects cursors that do not match the requested sort or filters", () => {
  const cursor = encodeCursor({ field: "title", direction: "asc", value: "A title", documentNumber: "2026-00001", filterKey: documentFilterKey("", null, null) });
  const parsed = parseDocumentQuery(new URLSearchParams({ sort: "-title", "page[cursor]": cursor }));
  assert.equal(parsed.ok, false);
  assert.equal(parsed.parameter, "page[cursor]");

  const filterMismatch = parseDocumentQuery(new URLSearchParams({ "filter[q]": "different search", sort: "title", "page[cursor]": cursor }));
  assert.equal(filterMismatch.ok, false);
  assert.equal(filterMismatch.parameter, "page[cursor]");
});
