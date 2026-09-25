import assert from "node:assert/strict";
import test from "node:test";
import { DocumentLoadError, documentErrorMessage } from "../lib/documents/errors.ts";

test("only transient database and network failures are retryable", () => {
  assert.equal(new DocumentLoadError("DATABASE_UNAVAILABLE", "").retryable, true);
  assert.equal(new DocumentLoadError("NETWORK_ERROR", "").retryable, true);
  assert.equal(new DocumentLoadError("INVALID_QUERY", "").retryable, false);
  assert.equal(new DocumentLoadError("INVALID_RESPONSE", "").retryable, false);
});

test("documentErrorMessage gives each API failure a user-facing message", () => {
  assert.equal(documentErrorMessage(new DocumentLoadError("INVALID_QUERY", "Fix the search.")), "Fix the search.");
  assert.equal(documentErrorMessage(new DocumentLoadError("NOT_ACCEPTABLE", "")), "This request format isn’t supported.");
  assert.equal(documentErrorMessage(new DocumentLoadError("DATABASE_UNAVAILABLE", "")), "The document service is temporarily unavailable. Try again shortly.");
  assert.equal(documentErrorMessage(new DocumentLoadError("DATABASE_CONFIGURATION_ERROR", "")), "The document service is unavailable. Try again later.");
  assert.equal(documentErrorMessage(new DocumentLoadError("INTERNAL_SERVER_ERROR", "")), "Something went wrong while loading EPA rules.");
  assert.equal(documentErrorMessage(new DocumentLoadError("NETWORK_ERROR", "")), "We couldn’t reach the service. Check your connection and try again.");
  assert.equal(documentErrorMessage(new DocumentLoadError("INVALID_RESPONSE", "")), "The service returned a response we couldn’t read.");
  assert.equal(documentErrorMessage(new Error("unknown")), "We couldn’t load the EPA rules. Try again.");
});
