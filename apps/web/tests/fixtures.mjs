export function makeDocumentPage() {
  return {
    jsonapi: { version: "1.1" },
    links: { self: "/api/documents", next: null },
    data: [{
      type: "documents",
      id: "2026-00001",
      attributes: {
        document_number: "2026-00001",
        title: "EPA rule fixture",
        type: "Rule",
        publication_date: "2026-09-24",
        effective_on: null,
        signing_date: null,
        comments_close_on: null,
        abstract: "A test rule.",
        action: null,
        agency_names: ["Environmental Protection Agency"],
        citation: "91 FR 1000",
        docket_ids: null,
        cfr_references: [{ title: "40", part: "52" }],
        html_url: "https://www.federalregister.gov/documents/2026/09/24/2026-00001",
        pdf_url: "https://www.federalregister.gov/documents/2026/09/24/2026-00001.pdf",
      },
    }],
    meta: {
      request_id: "request-123",
      page: { size: 20, hasMore: false },
      ingest: { last_successful_at: null, latest_run: null },
    },
  };
}

export function makeApiError(overrides = {}) {
  return {
    jsonapi: { version: "1.1" },
    meta: { request_id: "request-456" },
    errors: [{
      status: "400",
      code: "INVALID_QUERY",
      title: "Invalid query parameter",
      detail: "Sort by one of: title.",
      source: { parameter: "sort" },
    }],
    ...overrides,
  };
}
