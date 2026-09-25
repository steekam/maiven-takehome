import assert from "node:assert/strict";
import test from "node:test";
import {
  documentApiErrorResponseSchema,
  documentPageSchema,
  responseMetaSchema,
} from "../lib/documents/schemas.ts";
import { makeApiError, makeDocumentPage } from "./fixtures.mjs";

test("accepts the document collection response shape", () => {
  assert.equal(documentPageSchema.safeParse(makeDocumentPage()).success, true);
});

test("rejects a malformed document collection response", () => {
  const payload = makeDocumentPage();
  payload.data[0].attributes.title = 42;
  assert.equal(documentPageSchema.safeParse(payload).success, false);
});

test("accepts API errors with request metadata", () => {
  const parsed = documentApiErrorResponseSchema.safeParse(makeApiError());
  assert.equal(parsed.success, true);
  assert.equal(parsed.data.errors[0].code, "INVALID_QUERY");
  assert.equal(responseMetaSchema.safeParse(makeApiError()).data.meta.request_id, "request-456");
});

test("rejects unknown API error codes and empty error lists", () => {
  const unknownCode = makeApiError();
  unknownCode.errors[0].code = "UNKNOWN_ERROR";
  assert.equal(documentApiErrorResponseSchema.safeParse(unknownCode).success, false);

  const emptyErrors = makeApiError({ errors: [] });
  assert.equal(documentApiErrorResponseSchema.safeParse(emptyErrors).success, false);
});
