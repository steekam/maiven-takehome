import {
  context,
  metrics,
  SpanStatusCode,
  trace,
  type Span,
} from "@opentelemetry/api";

const meter = metrics.getMeter("maiven.web");
const apiRequests = meter.createCounter("maiven.api.requests", {
  description: "HTTP requests handled by the Maiven web API",
});
const apiDuration = meter.createHistogram("maiven.api.request.duration", {
  unit: "ms",
  description: "Duration of Maiven web API requests",
});
const databaseOperations = meter.createCounter("maiven.db.operations", {
  description: "Database operations executed by the Maiven web API",
});
const databaseDuration = meter.createHistogram("maiven.db.operation.duration", {
  unit: "ms",
  description: "Duration of Maiven web API database operations",
});

const tracer = trace.getTracer("maiven.web");

export function getTraceCorrelation() {
  const span = trace.getSpan(context.active());
  const spanContext = span?.spanContext();
  if (!spanContext || !trace.isSpanContextValid(spanContext)) return {};

  return {
    trace_id: spanContext.traceId,
    span_id: spanContext.spanId,
    trace_flags: spanContext.traceFlags,
  };
}

export function getErrorCode(error: unknown): string | null {
  const seen = new Set<object>();
  let current: unknown = error;

  while (typeof current === "object" && current !== null && !seen.has(current)) {
    seen.add(current);
    if ("code" in current && typeof current.code === "string") return current.code;
    current = "cause" in current ? current.cause : undefined;
  }

  return null;
}

export function recordCurrentException(error: unknown) {
  const span = trace.getSpan(context.active());
  if (!span) return;

  span.recordException({
    name: error instanceof Error ? error.name : "UnknownError",
    message: "Operation failed",
  });
  const errorCode = getErrorCode(error);
  if (errorCode) span.setAttribute("error.code", errorCode);
  span.setStatus({ code: SpanStatusCode.ERROR });
}

export function withApiSpan(operation: (span: Span) => Promise<Response>) {
  const startedAt = performance.now();

  return tracer.startActiveSpan("GET /api/documents", {
    attributes: {
      "http.request.method": "GET",
      "http.route": "/api/documents",
    },
  }, async (span) => {
    let statusCode = 500;
    try {
      const response = await operation(span);
      statusCode = response.status;
      span.setAttribute("http.response.status_code", statusCode);
      if (statusCode >= 500) span.setStatus({ code: SpanStatusCode.ERROR });
      return response;
    } catch (error) {
      recordCurrentException(error);
      throw error;
    } finally {
      const attributes = {
        route: "/api/documents",
        method: "GET",
        status_class: `${Math.floor(statusCode / 100)}xx`,
      };
      apiRequests.add(1, attributes);
      apiDuration.record(performance.now() - startedAt, attributes);
      span.end();
    }
  });
}

export function withDatabaseSpan<T>(
  name: "documents.search" | "documents.ingest_freshness",
  operation: (span: Span) => Promise<T>,
) {
  const startedAt = performance.now();

  return tracer.startActiveSpan(name, {
    attributes: {
      "db.system.name": "postgresql",
      "db.operation.name": "SELECT",
      "db.collection.name": name === "documents.search" ? "documents" : "ingest_runs",
    },
  }, async (span) => {
    let status = "ok";
    try {
      return await operation(span);
    } catch (error) {
      status = "error";
      recordCurrentException(error);
      throw error;
    } finally {
      const attributes = { operation: name, status };
      databaseOperations.add(1, attributes);
      databaseDuration.record(performance.now() - startedAt, attributes);
      span.end();
    }
  });
}
