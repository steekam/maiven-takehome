import { randomUUID } from "node:crypto";
import { acceptsJsonApi, mediaType } from "@/lib/documents/accept";
import type { DocumentPage } from "@/lib/documents/schemas";
import type { DocumentApiErrorCode } from "@/lib/documents/errors";
import { parseDocumentQuery } from "@/lib/documents/query";
import { readDocuments, readIngestFreshness } from "@/lib/documents/read";
import { DatabaseConfigurationError } from "@/lib/server/db";
import { logger } from "@/lib/server/logger";
import { getErrorCode, getTraceCorrelation, recordCurrentException, withApiSpan } from "@/lib/server/telemetry";

function jsonApi(body: unknown, status = 200) {
  return Response.json(body, {
    status,
    headers: {
      "Content-Type": mediaType,
      "Cache-Control": "no-store",
    },
  });
}

type ApiFailure = {
  status: 400 | 406 | 503 | 500;
  code: DocumentApiErrorCode;
  title: string;
  detail: string;
  parameter?: string;
};

function errorDocument(requestId: string, failure: ApiFailure) {
  return jsonApi({
    jsonapi: { version: "1.1" },
    meta: { request_id: requestId },
    errors: [{
      status: String(failure.status),
      code: failure.code,
      title: failure.title,
      detail: failure.detail,
      ...(failure.parameter ? { source: { parameter: failure.parameter } } : {}),
    }],
  }, failure.status);
}

const unavailableDatabaseCodes = new Set([
  "53300",
  "57P01",
  "57P02",
  "57P03",
  "ECONNREFUSED",
  "ECONNRESET",
  "ETIMEDOUT",
  "ENETUNREACH",
  "EHOSTUNREACH",
  "ENOTFOUND",
  "EAI_AGAIN",
]);

function isDatabaseUnavailable(error: unknown) {
  if (error instanceof DatabaseConfigurationError) return true;
  const code = getErrorCode(error);
  return code !== null && (code.startsWith("08") || unavailableDatabaseCodes.has(code));
}

export async function GET(request: Request) {
  return withApiSpan(async (span) => {
    const requestId = randomUUID();
    span.setAttribute("request.id", requestId);
    if (!acceptsJsonApi(request.headers.get("accept"))) {
      return errorDocument(requestId, {
        status: 406,
        code: "NOT_ACCEPTABLE",
        title: "Not Acceptable",
        detail: `Request ${mediaType}.`,
        parameter: "Accept",
      });
    }

    const parsed = parseDocumentQuery(new URL(request.url).searchParams);
    if (!parsed.ok) {
      return errorDocument(requestId, {
        status: 400,
        code: "INVALID_QUERY",
        title: "Invalid query parameter",
        detail: parsed.detail,
        parameter: parsed.parameter,
      });
    }

    span.setAttribute("search.enabled", Boolean(parsed.query.q));
    span.setAttribute("filter.publication_date", Boolean(parsed.query.dateFrom || parsed.query.dateTo));
    span.setAttribute("sort.field", parsed.query.sort);
    span.setAttribute("sort.direction", parsed.query.direction);
    span.setAttribute("pagination.page_size", parsed.query.pageSize);

    try {
      const [result, ingest] = await Promise.all([
        readDocuments(parsed.query),
        readIngestFreshness(),
      ]);
      span.setAttribute("documents.result_count", result.rows.length);
      span.setAttribute("documents.has_more", result.hasMore);
      const self = new URL(request.url);

      const next = result.nextCursor ? new URL(request.url) : null;
      if (next && result.nextCursor) next.searchParams.set("page[cursor]", result.nextCursor);

      const body: DocumentPage = {
        jsonapi: { version: "1.1" },
        links: {
          self: `${self.pathname}${self.search}`,
          next: next ? `${next.pathname}${next.search}` : null,
        },
        meta: {
          request_id: requestId,
          page: { size: parsed.query.pageSize, hasMore: result.hasMore },
          ingest,
        },
        data: result.rows.map((document) => ({
          type: "documents",
          id: document.documentNumber,
          attributes: {
            document_number: document.documentNumber,
            title: document.title,
            type: document.type,
            publication_date: document.publicationDate,
            effective_on: document.effectiveOn,
            signing_date: document.signingDate,
            comments_close_on: document.commentsCloseOn,
            abstract: document.abstract,
            action: document.action,
            agency_names: document.agencyNames,
            citation: document.citation,
            docket_ids: document.docketIds,
            cfr_references: document.cfrReferences,
            html_url: document.htmlUrl,
            pdf_url: document.pdfUrl,
          },
        })),
      };
      return jsonApi(body);
    } catch (error) {
      recordCurrentException(error);
      const errorCode: DocumentApiErrorCode = error instanceof DatabaseConfigurationError
        ? "DATABASE_CONFIGURATION_ERROR"
        : isDatabaseUnavailable(error)
          ? "DATABASE_UNAVAILABLE"
          : "INTERNAL_SERVER_ERROR";
      const traceCorrelation = getTraceCorrelation();
      logger.error({
        event: "documents_query_failed",
        request_id: requestId,
        ...traceCorrelation,
        ...(traceCorrelation.trace_id ? { tid: traceCorrelation.trace_id } : {}),
        error_code: errorCode,
        error_name: error instanceof Error ? error.name : "UnknownError",
        database_code: getErrorCode(error),
      }, "Document search failed");

      return errorDocument(requestId, errorCode === "DATABASE_UNAVAILABLE" || errorCode === "DATABASE_CONFIGURATION_ERROR"
        ? {
            status: 503,
            code: errorCode,
            title: "Service Unavailable",
            detail: error instanceof DatabaseConfigurationError
              ? "The document database is not configured."
              : "The document database is temporarily unavailable.",
          }
        : {
            status: 500,
            code: "INTERNAL_SERVER_ERROR",
            title: "Internal Server Error",
            detail: "Unable to load documents.",
          });
    }
  });
}
