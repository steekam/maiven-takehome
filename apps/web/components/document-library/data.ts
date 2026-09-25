import { documentApiErrorResponseSchema, documentPageSchema, responseMetaSchema, type DocumentPage, type JsonValue } from "@/lib/documents/schemas";
import { DocumentLoadError } from "@/lib/documents/errors";

export function formatCfrReferences(references: JsonValue[] | null) {
  return references?.map((value) => {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") return Object.values(value).filter((part) => typeof part === "string").join(" · ");
    return "";
  }).filter(Boolean).join(", ");
}

export function makeApiUrl(query: string, dateFrom: string, dateTo: string, sort: string) {
  const params = new URLSearchParams();
  if (query) params.set("filter[q]", query);
  if (dateFrom) params.set("filter[publication_date][gte]", dateFrom);
  if (dateTo) params.set("filter[publication_date][lte]", dateTo);
  params.set("sort", sort);
  params.set("page[size]", "20");
  return `/api/documents?${params.toString()}`;
}

function apiError(payload: unknown, status: number): DocumentLoadError {
  const requestId = responseRequestId(payload);
  const response = documentApiErrorResponseSchema.safeParse(payload);
  const error = response.success ? response.data.errors.at(0) : null;
  if (!error) {
    return new DocumentLoadError("INVALID_RESPONSE", "", status, requestId);
  }

  return new DocumentLoadError(error.code, error.detail ?? "Your search or filters are invalid.", status, requestId);
}

function responseRequestId(payload: unknown) {
  const response = responseMetaSchema.safeParse(payload);
  return response.success ? response.data.meta?.request_id ?? null : null;
}

export async function fetchPage(url: string, signal: AbortSignal): Promise<DocumentPage> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/vnd.api+json" }, signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new DocumentLoadError("NETWORK_ERROR", "");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal.aborted) throw error;
    throw new DocumentLoadError("INVALID_RESPONSE", "", response.status);
  }

  if (!response.ok) throw apiError(payload, response.status);
  const documentPage = documentPageSchema.safeParse(payload);
  if (!documentPage.success) {
    throw new DocumentLoadError("INVALID_RESPONSE", "", response.status, responseRequestId(payload));
  }
  return documentPage.data;
}
