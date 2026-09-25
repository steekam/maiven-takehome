import { DocumentLoadError, isDocumentApiErrorCode } from "@/lib/documents/errors";
import type { DocumentPage, JsonValue } from "@/lib/documents/contracts";

type ApiErrorPayload = {
  meta?: { request_id?: unknown } | null;
  errors?: { code?: unknown; detail?: unknown }[] | null;
} | null;

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
  const body = payload as ApiErrorPayload;
  const requestId = typeof body?.meta?.request_id === "string" ? body.meta.request_id : null;
  const firstError = Array.isArray(body?.errors) ? body.errors[0] : null;
  if (!firstError || !isDocumentApiErrorCode(firstError.code)) {
    return new DocumentLoadError("INVALID_RESPONSE", "", status, requestId);
  }

  const message = typeof firstError.detail === "string" ? firstError.detail : "Your search or filters are invalid.";
  return new DocumentLoadError(firstError.code, message, status, requestId);
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
  return payload as DocumentPage;
}
