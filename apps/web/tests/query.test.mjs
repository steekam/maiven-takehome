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

test("uses an explicit minus prefix for descending sort", () => {
  const parsed = parseDocumentQuery(new URLSearchParams({ sort: "-title" }));
  assert.equal(parsed.ok, true);
  assert.equal(parsed.query.sort, "title");
  assert.equal(parsed.query.direction, "desc");
});

test("trims search text and rejects text longer than 200 characters", () => {
  const trimmed = parseDocumentQuery(new URLSearchParams({ "filter[q]": "  clean air  " }));
  assert.equal(trimmed.ok, true);
  assert.equal(trimmed.query.q, "clean air");

  const tooLong = parseDocumentQuery(new URLSearchParams({ "filter[q]": "x".repeat(201) }));
  assert.equal(tooLong.ok, false);
  assert.equal(tooLong.parameter, "filter[q]");
  assert.equal(tooLong.detail, "Search text must be 200 characters or fewer.");
});

test("accepts page-size boundaries and reports invalid values against page[size]", () => {
  for (const size of ["1", "20"]) {
    const parsed = parseDocumentQuery(new URLSearchParams({ "page[size]": size }));
    assert.equal(parsed.ok, true);
    assert.equal(parsed.query.pageSize, Number(size));
  }

  for (const size of ["", "0", "21", "1.5", "abc"]) {
    const parsed = parseDocumentQuery(new URLSearchParams({ "page[size]": size }));
    assert.equal(parsed.ok, false);
    assert.equal(parsed.parameter, "page[size]");
    assert.equal(parsed.detail, "Page size must be an integer from 1 to 20.");
  }
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

test("round-trips a valid cursor for the same sort and filters", () => {
  const cursor = encodeCursor({
    field: "title",
    direction: "desc",
    value: "Zoning rule",
    documentNumber: "2026-00001",
    filterKey: documentFilterKey("clean air", "2026-01-01", "2026-01-31"),
  });
  const parsed = parseDocumentQuery(new URLSearchParams({
    "filter[q]": " clean air ",
    "filter[publication_date][gte]": "2026-01-01",
    "filter[publication_date][lte]": "2026-01-31",
    sort: "-title",
    "page[cursor]": cursor,
  }));

  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.query.cursor, {
    field: "title",
    direction: "desc",
    value: "Zoning rule",
    documentNumber: "2026-00001",
    filterKey: documentFilterKey("clean air", "2026-01-01", "2026-01-31"),
  });
});

test("rejects malformed and structurally invalid cursor tokens", () => {
  const invalidTokens = [
    "not-json",
    Buffer.from("[]").toString("base64url"),
    Buffer.from(JSON.stringify({
      field: "updated_at",
      direction: "asc",
      value: "x",
      documentNumber: "2026-00001",
      filterKey: "[]",
    })).toString("base64url"),
  ];

  for (const token of invalidTokens) {
    const parsed = parseDocumentQuery(new URLSearchParams({ "page[cursor]": token }));
    assert.equal(parsed.ok, false);
    assert.equal(parsed.parameter, "page[cursor]");
    assert.equal(parsed.detail, "The cursor is invalid.");
  }
});

test("reports date validation errors with the matching filter parameter", () => {
  const invalidDate = parseDocumentQuery(new URLSearchParams({
    "filter[publication_date][lte]": "2026-02-30",
  }));
  assert.equal(invalidDate.ok, false);
  assert.equal(invalidDate.parameter, "filter[publication_date][lte]");
  assert.equal(invalidDate.detail, "Use a valid date in YYYY-MM-DD format.");

  const reversedRange = parseDocumentQuery(new URLSearchParams({
    "filter[publication_date][gte]": "2026-02-02",
    "filter[publication_date][lte]": "2026-02-01",
  }));
  assert.equal(reversedRange.ok, false);
  assert.equal(reversedRange.parameter, "filter[publication_date]");
  assert.equal(reversedRange.detail, "The start date must be on or before the end date.");
});
