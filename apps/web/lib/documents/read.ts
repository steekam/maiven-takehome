import { and, asc, desc, eq, gt, isNotNull, lt, or, sql, type SQLWrapper } from "drizzle-orm";
import { documents, ingestRuns } from "@maiven/db/schema";
import { getDatabase } from "@/lib/server/db";
import { withDatabaseSpan } from "@/lib/server/telemetry";
import { documentFilterKey, encodeCursor, type DocumentQuery, type DocumentSortField } from "./query";

const sortExpressions: Record<DocumentSortField, SQLWrapper> = {
  publication_date: documents.publicationDate,
  document_number: documents.documentNumber,
  title: documents.title,
  type: documents.type,
  agency: sql<string>`lower(coalesce(${documents.agencyNames}::text, ''))`,
};

export function readDocuments(query: DocumentQuery) {
  return withDatabaseSpan("documents.search", async (span) => {
    span.setAttribute("search.enabled", Boolean(query.q));
    span.setAttribute("filter.publication_date", Boolean(query.dateFrom || query.dateTo));
    span.setAttribute("sort.field", query.sort);
    span.setAttribute("sort.direction", query.direction);
    span.setAttribute("pagination.page_size", query.pageSize);
    return queryDocuments(query);
  });
}

export function buildCursorCondition(query: DocumentQuery): SQLWrapper | undefined {
  const cursor = query.cursor;
  if (!cursor) return undefined;

  const sortExpression = sortExpressions[query.sort];
  const primaryAfter = query.direction === "asc"
    ? gt(sortExpression, cursor.value)
    : lt(sortExpression, cursor.value);
  if (query.sort === "document_number") return primaryAfter;

  return or(
    primaryAfter,
    and(eq(sortExpression, cursor.value), lt(documents.documentNumber, cursor.documentNumber)),
  )!;
}

async function queryDocuments(query: DocumentQuery) {
  const sortExpression = sortExpressions[query.sort];
  const conditions: SQLWrapper[] = [];

  if (query.q) {
    const documentSearch = sql`to_tsvector('english', coalesce(${documents.title}, '') || ' ' || coalesce(${documents.abstract}, ''))`;
    conditions.push(sql`${documentSearch} @@ websearch_to_tsquery('english', ${query.q})`);
  }
  if (query.dateFrom) conditions.push(sql`${documents.publicationDate} >= ${query.dateFrom}`);
  if (query.dateTo) conditions.push(sql`${documents.publicationDate} <= ${query.dateTo}`);

  const cursorCondition = buildCursorCondition(query);
  if (cursorCondition) conditions.push(cursorCondition);

  const order = query.direction === "asc" ? asc(sortExpression) : desc(sortExpression);
  const rows = await getDatabase()
    .select({
      documentNumber: documents.documentNumber,
      title: documents.title,
      type: documents.type,
      publicationDate: documents.publicationDate,
      effectiveOn: documents.effectiveOn,
      signingDate: documents.signingDate,
      commentsCloseOn: documents.commentsCloseOn,
      abstract: documents.abstract,
      action: documents.action,
      agencyNames: documents.agencyNames,
      citation: documents.citation,
      docketIds: documents.docketIds,
      cfrReferences: documents.cfrReferences,
      htmlUrl: documents.htmlUrl,
      publicInspectionPdfUrl: documents.publicInspectionPdfUrl,
      pdfUrl: documents.pdfUrl,
      sortValue: sql<string>`${sortExpression}`.as("sort_value"),
    })
    .from(documents)
    .where(conditions.length ? and(...conditions) : undefined)
    .orderBy(order, ...(query.sort === "document_number" ? [] : [desc(documents.documentNumber)]))
    .limit(query.pageSize + 1);

  const hasMore = rows.length > query.pageSize;
  const page = rows.slice(0, query.pageSize);
  const last = page.at(-1);
  const nextCursor = hasMore && last
    ? encodeCursor({
        field: query.sort,
        direction: query.direction,
        value: last.sortValue,
        documentNumber: last.documentNumber,
        filterKey: documentFilterKey(query.q, query.dateFrom, query.dateTo),
      })
    : null;

  return {
    rows: page.map(({ sortValue: _sortValue, ...row }) => ({
      ...row,
      pdfUrl: row.publicInspectionPdfUrl ?? row.pdfUrl,
    })),
    hasMore,
    nextCursor,
  };
}

export function readIngestFreshness() {
  return withDatabaseSpan("documents.ingest_freshness", queryIngestFreshness);
}

async function queryIngestFreshness() {
  const db = getDatabase();
  const [lastSuccessRows, latestRunRows] = await Promise.all([
    db.select({ finishedAt: ingestRuns.finishedAt })
      .from(ingestRuns)
      .where(and(eq(ingestRuns.status, "succeeded"), isNotNull(ingestRuns.finishedAt)))
      .orderBy(desc(ingestRuns.finishedAt))
      .limit(1),
    db.select({
      status: ingestRuns.status,
      completionReason: ingestRuns.completionReason,
      startedAt: ingestRuns.startedAt,
      finishedAt: ingestRuns.finishedAt,
    })
      .from(ingestRuns)
      .orderBy(desc(ingestRuns.startedAt))
      .limit(1),
  ]);

  const lastSuccessfulAt = lastSuccessRows[0]?.finishedAt;
  const latestRun = latestRunRows[0];
  return {
    last_successful_at: lastSuccessfulAt?.toISOString() ?? null,
    latest_run: latestRun
      ? {
          status: latestRun.status,
          completion_reason: latestRun.completionReason,
          started_at: latestRun.startedAt.toISOString(),
          finished_at: latestRun.finishedAt?.toISOString() ?? null,
        }
      : null,
  };
}
