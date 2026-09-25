const defaultRow = {
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
  htmlUrl: "https://www.federalregister.gov/documents/2026/09/24/2026-00001",
  publicInspectionPdfUrl: null,
  pdfUrl: "https://www.federalregister.gov/documents/2026/09/24/2026-00001.pdf",
};

let documentReader = async () => ({ rows: [defaultRow], hasMore: true, nextCursor: "cursor-token" });
let freshnessReader = async () => ({ last_successful_at: null, latest_run: null });
let lastQuery;

export function configureDocumentReader(reader) {
  documentReader = reader;
}

export function resetDocumentReader() {
  documentReader = async () => ({ rows: [defaultRow], hasMore: true, nextCursor: "cursor-token" });
  freshnessReader = async () => ({ last_successful_at: null, latest_run: null });
  lastQuery = undefined;
}

export function getLastQuery() {
  return lastQuery;
}

export async function readDocuments(query) {
  lastQuery = query;
  return documentReader(query);
}

export async function readIngestFreshness() {
  return freshnessReader();
}
