import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { GET } from "../app/api/documents/route.ts";
import { DatabaseConfigurationError } from "../lib/server/db.ts";
import { documentPageSchema } from "../lib/documents/schemas.ts";
import { getLastQuery, configureDocumentReader, resetDocumentReader } from "./stubs/document-read.mjs";

afterEach(resetDocumentReader);

test("GET returns a valid collection and preserves query state in links.next", async () => {
  const request = new Request("http://localhost/api/documents?filter%5Bq%5D=air&sort=-title");
  const response = await GET(request);
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "application/vnd.api+json");
  assert.equal(documentPageSchema.safeParse(body).success, true);
  assert.equal(body.data[0].id, "2026-00001");
  assert.equal(body.meta.page.hasMore, true);
  assert.equal(new URL(body.links.next, request.url).searchParams.get("page[cursor]"), "cursor-token");
  assert.equal(new URL(body.links.next, request.url).searchParams.get("sort"), "-title");
  assert.deepEqual(
    { q: getLastQuery().q, sort: getLastQuery().sort, direction: getLastQuery().direction },
    { q: "air", sort: "title", direction: "desc" },
  );
});

test("GET returns JSON:API 400 details for invalid query parameters", async () => {
  const response = await GET(new Request(
    "http://localhost/api/documents?filter%5Beffective_on%5D=2026-01-01",
  ));
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.equal(body.errors[0].code, "INVALID_QUERY");
  assert.equal(body.errors[0].source.parameter, "filter[effective_on]");
  assert.equal(getLastQuery(), undefined);
});

test("GET returns 406 when the client rejects JSON:API", async () => {
  const response = await GET(new Request("http://localhost/api/documents", {
    headers: { Accept: "text/html" },
  }));
  const body = await response.json();

  assert.equal(response.status, 406);
  assert.equal(body.errors[0].code, "NOT_ACCEPTABLE");
  assert.equal(body.errors[0].source.parameter, "Accept");
});

test("GET maps database connection errors to a correlated 503 response", async () => {
  configureDocumentReader(async () => {
    throw Object.assign(new Error("Connection refused"), { code: "ECONNREFUSED" });
  });

  const response = await GET(new Request("http://localhost/api/documents"));
  const body = await response.json();

  assert.equal(response.status, 503);
  assert.equal(body.errors[0].code, "DATABASE_UNAVAILABLE");
  assert.equal(typeof body.meta.request_id, "string");
});

test("GET reports a missing database configuration as a correlated 503", async () => {
  configureDocumentReader(async () => {
    throw new DatabaseConfigurationError();
  });

  const response = await GET(new Request("http://localhost/api/documents"));
  const body = await response.json();

  assert.equal(response.status, 503);
  assert.equal(body.errors[0].code, "DATABASE_CONFIGURATION_ERROR");
  assert.equal(body.errors[0].detail, "The document database is not configured.");
  assert.equal(typeof body.meta.request_id, "string");
});

test("GET maps unexpected failures to a correlated 500", async () => {
  configureDocumentReader(async () => {
    throw new Error("unexpected failure");
  });

  const response = await GET(new Request("http://localhost/api/documents"));
  const body = await response.json();

  assert.equal(response.status, 500);
  assert.equal(body.errors[0].code, "INTERNAL_SERVER_ERROR");
  assert.equal(body.errors[0].detail, "Unable to load documents.");
  assert.equal(typeof body.meta.request_id, "string");
});
