export const documentSortFields = [
  "publication_date",
  "document_number",
  "title",
  "type",
  "agency",
] as const;

export type DocumentSortField = (typeof documentSortFields)[number];
export type SortDirection = "asc" | "desc";

export type DocumentQuery = {
  q: string;
  dateFrom: string | null;
  dateTo: string | null;
  sort: DocumentSortField;
  direction: SortDirection;
  pageSize: number;
  cursor: DocumentCursor | null;
};

export type DocumentCursor = {
  field: DocumentSortField;
  direction: SortDirection;
  value: string;
  documentNumber: string;
  filterKey: string;
};

export type ParsedDocumentQuery =
  | { ok: true; query: DocumentQuery }
  | { ok: false; parameter: string; detail: string };

const defaultPageSize = 20;
const maxPageSize = 20;
const supportedFilters = new Set([
  "filter[q]",
  "filter[publication_date][gte]",
  "filter[publication_date][lte]",
]);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

export function documentFilterKey(q: string, dateFrom: string | null, dateTo: string | null): string {
  return JSON.stringify([q, dateFrom, dateTo]);
}

function isDate(value: string): boolean {
  if (!datePattern.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function decodeCursor(value: string): DocumentCursor | null {
  try {
    const decoded: unknown = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (typeof decoded !== "object" || decoded === null) return null;
    const cursor = decoded as Record<string, unknown>;
    if (
      typeof cursor.field !== "string" ||
      !documentSortFields.includes(cursor.field as DocumentSortField) ||
      (cursor.direction !== "asc" && cursor.direction !== "desc") ||
      typeof cursor.value !== "string" ||
      typeof cursor.documentNumber !== "string" ||
      typeof cursor.filterKey !== "string"
    ) {
      return null;
    }
    return {
      field: cursor.field as DocumentSortField,
      direction: cursor.direction,
      value: cursor.value,
      documentNumber: cursor.documentNumber,
      filterKey: cursor.filterKey,
    };
  } catch {
    return null;
  }
}

export function encodeCursor(cursor: DocumentCursor): string {
  return Buffer.from(JSON.stringify(cursor)).toString("base64url");
}

export function parseDocumentQuery(params: URLSearchParams): ParsedDocumentQuery {
  for (const parameter of params.keys()) {
    if (parameter.startsWith("filter[") && !supportedFilters.has(parameter)) {
      return { ok: false, parameter, detail: "This filter is not supported." };
    }
  }

  const q = (params.get("filter[q]") ?? "").trim();
  if (q.length > 200) {
    return { ok: false, parameter: "filter[q]", detail: "Search text must be 200 characters or fewer." };
  }

  const dateFrom = params.get("filter[publication_date][gte]");
  const dateTo = params.get("filter[publication_date][lte]");
  if (dateFrom && !isDate(dateFrom)) {
    return { ok: false, parameter: "filter[publication_date][gte]", detail: "Use a valid date in YYYY-MM-DD format." };
  }
  if (dateTo && !isDate(dateTo)) {
    return { ok: false, parameter: "filter[publication_date][lte]", detail: "Use a valid date in YYYY-MM-DD format." };
  }
  if (dateFrom && dateTo && dateFrom > dateTo) {
    return { ok: false, parameter: "filter[publication_date]", detail: "The start date must be on or before the end date." };
  }

  const sortParam = params.get("sort") ?? "-publication_date";
  const direction: SortDirection = sortParam.startsWith("-") ? "desc" : "asc";
  const sort = (direction === "desc" ? sortParam.slice(1) : sortParam) as DocumentSortField;
  if (!documentSortFields.includes(sort)) {
    return { ok: false, parameter: "sort", detail: `Sort by one of: ${documentSortFields.join(", ")}.` };
  }

  const pageSizeParam = params.get("page[size]");
  const pageSize = pageSizeParam === null ? defaultPageSize : Number(pageSizeParam);
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > maxPageSize) {
    return { ok: false, parameter: "page[size]", detail: `Page size must be an integer from 1 to ${maxPageSize}.` };
  }

  const cursorParam = params.get("page[cursor]");
  const cursor = cursorParam ? decodeCursor(cursorParam) : null;
  if (cursorParam && !cursor) {
    return { ok: false, parameter: "page[cursor]", detail: "The cursor is invalid." };
  }
  if (cursor && (cursor.field !== sort || cursor.direction !== direction)) {
    return { ok: false, parameter: "page[cursor]", detail: "The cursor does not match the requested sort." };
  }
  if (cursor && cursor.filterKey !== documentFilterKey(q, dateFrom, dateTo)) {
    return { ok: false, parameter: "page[cursor]", detail: "The cursor does not match the requested filters." };
  }

  return {
    ok: true,
    query: {
      q,
      dateFrom,
      dateTo,
      sort,
      direction,
      pageSize,
      cursor,
    },
  };
}
