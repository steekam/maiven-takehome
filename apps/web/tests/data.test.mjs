import assert from "node:assert/strict";
import test from "node:test";
import { fetchPage, formatCfrReferences, makeApiUrl } from "../components/document-library/data.ts";
import { DocumentLoadError } from "../lib/documents/errors.ts";
import { makeApiError, makeDocumentPage } from "./fixtures.mjs";

async function withFetch(implementation, run) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = implementation;
  try {
    return await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status });
}

test("makeApiUrl includes only active filters and keeps the selected sort", () => {
  const url = new URL(makeApiUrl("ozone", "2026-09-01", "", "-title"), "http://localhost");

  assert.equal(url.pathname, "/api/documents");
  assert.deepEqual([...url.searchParams], [
    ["filter[q]", "ozone"],
    ["filter[publication_date][gte]", "2026-09-01"],
    ["sort", "-title"],
    ["page[size]", "20"],
  ]);
});

test("formatCfrReferences keeps strings and joins string-valued reference fields", () => {
  assert.equal(
    formatCfrReferences([{ title: "40", part: "52", section: 1 }, "42", null, 7]),
    "40 · 52, 42",
  );
  assert.equal(formatCfrReferences([]), "");
  assert.equal(formatCfrReferences(null), undefined);
});

test("fetchPage requests JSON:API and returns a validated document page", async () => {
  const page = makeDocumentPage();
  const result = await withFetch(async (_url, options) => {
    assert.equal(options.headers.Accept, "application/vnd.api+json");
    return jsonResponse(page);
  }, () => fetchPage("/api/documents", new AbortController().signal));

  assert.deepEqual(result, page);
});

test("fetchPage maps invalid success payloads to INVALID_RESPONSE and preserves request ID", async () => {
  const payload = { meta: { request_id: "request-invalid" }, data: [] };
  await withFetch(async () => jsonResponse(payload), async () => {
    await assert.rejects(
      fetchPage("/api/documents", new AbortController().signal),
      (error) => error instanceof DocumentLoadError
        && error.code === "INVALID_RESPONSE"
        && error.status === 200
        && error.requestId === "request-invalid",
    );
  });
});

test("fetchPage maps valid API error payloads to DocumentLoadError", async () => {
  await withFetch(async () => jsonResponse(makeApiError(), 400), async () => {
    await assert.rejects(
      fetchPage("/api/documents?sort=invalid", new AbortController().signal),
      (error) => error instanceof DocumentLoadError
        && error.code === "INVALID_QUERY"
        && error.status === 400
        && error.requestId === "request-456"
        && error.message === "Sort by one of: title.",
    );
  });
});

test("fetchPage rejects malformed JSON and unknown API error codes", async () => {
  await withFetch(async () => new Response("not-json", { status: 502 }), async () => {
    await assert.rejects(
      fetchPage("/api/documents", new AbortController().signal),
      (error) => error instanceof DocumentLoadError && error.code === "INVALID_RESPONSE" && error.status === 502,
    );
  });

  const unknownCode = makeApiError();
  unknownCode.errors[0].code = "UNKNOWN_ERROR";
  await withFetch(async () => jsonResponse(unknownCode, 500), async () => {
    await assert.rejects(
      fetchPage("/api/documents", new AbortController().signal),
      (error) => error instanceof DocumentLoadError
        && error.code === "INVALID_RESPONSE"
        && error.requestId === "request-456",
    );
  });
});

test("fetchPage preserves abort errors instead of classifying them as network failures", async () => {
  const controller = new AbortController();
  const abortError = new Error("aborted");
  controller.abort();

  await withFetch(async () => { throw abortError; }, async () => {
    await assert.rejects(fetchPage("/api/documents", controller.signal), (error) => error === abortError);
  });
});

test("fetchPage classifies transport failures as retryable network errors", async () => {
  await withFetch(async () => { throw new Error("connection reset"); }, async () => {
    await assert.rejects(
      fetchPage("/api/documents", new AbortController().signal),
      (error) => error instanceof DocumentLoadError && error.code === "NETWORK_ERROR" && error.retryable,
    );
  });
});
