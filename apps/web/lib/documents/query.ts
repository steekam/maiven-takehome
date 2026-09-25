import { z } from "zod";

export const documentSortFields = [
  "publication_date",
  "document_number",
  "title",
  "type",
  "agency",
] as const;

const documentSortFieldSchema = z.enum(documentSortFields);
const sortDirectionSchema = z.enum(["asc", "desc"]);
const documentCursorSchema = z.object({
  field: documentSortFieldSchema,
  direction: sortDirectionSchema,
  value: z.string(),
  documentNumber: z.string(),
  filterKey: z.string(),
});

export type DocumentSortField = z.infer<typeof documentSortFieldSchema>;
export type SortDirection = z.infer<typeof sortDirectionSchema>;
export type DocumentCursor = z.infer<typeof documentCursorSchema>;

const defaultPageSize = 20;
const maxPageSize = 20;
const pageSizeError = `Page size must be an integer from 1 to ${maxPageSize}.`;
const supportedFilters = new Set([
  "filter[q]",
  "filter[publication_date][gte]",
  "filter[publication_date][lte]",
]);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

function isDate(value: string): boolean {
  if (!datePattern.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

const sortParameterSchema = z.string().default("-publication_date").transform((value, context) => {
  const direction: SortDirection = value.startsWith("-") ? "desc" : "asc";
  const field = direction === "desc" ? value.slice(1) : value;
  const parsedField = documentSortFieldSchema.safeParse(field);
  if (!parsedField.success) {
    context.addIssue({
      code: "custom",
      message: `Sort by one of: ${documentSortFields.join(", ")}.`,
    });
    return z.NEVER;
  }
  return { field: parsedField.data, direction };
});

const dateBoundSchema = z.string()
  .refine((value) => value === "" || isDate(value), {
    error: "Use a valid date in YYYY-MM-DD format.",
  })
  .nullable()
  .optional()
  .default(null);

const pageSizeSchema = z.preprocess(
  (value) => value === undefined ? defaultPageSize : Number(value),
  z.number({ error: pageSizeError })
    .int({ error: pageSizeError })
    .min(1, { error: pageSizeError })
    .max(maxPageSize, { error: pageSizeError }),
);

function decodeCursor(value: string): DocumentCursor | null {
  try {
    const decoded: unknown = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    const cursor = documentCursorSchema.safeParse(decoded);
    return cursor.success ? cursor.data : null;
  } catch {
    return null;
  }
}

const cursorParameterSchema = z.string().optional().default("").transform((value, context) => {
  if (!value) return null;
  const cursor = decodeCursor(value);
  if (!cursor) {
    context.addIssue({ code: "custom", message: "The cursor is invalid." });
    return z.NEVER;
  }
  return cursor;
});

const supportedFilterParametersSchema = z.array(z.string()).superRefine((parameters, context) => {
  const unsupported = parameters.find((parameter) =>
    parameter.startsWith("filter[") && !supportedFilters.has(parameter),
  );
  if (unsupported) {
    context.addIssue({
      code: "custom",
      path: [unsupported],
      message: "This filter is not supported.",
    });
  }
});

const documentQuerySchema = z.object({
  "filter[q]": z.string()
    .trim()
    .max(200, { error: "Search text must be 200 characters or fewer." })
    .optional()
    .default(""),
  "filter[publication_date][gte]": dateBoundSchema,
  "filter[publication_date][lte]": dateBoundSchema,
  sort: sortParameterSchema,
  "page[size]": pageSizeSchema,
  "page[cursor]": cursorParameterSchema,
}).superRefine((query, context) => {
  const dateFrom = query["filter[publication_date][gte]"];
  const dateTo = query["filter[publication_date][lte]"];
  if (dateFrom && dateTo && dateFrom > dateTo) {
    context.addIssue({
      code: "custom",
      path: ["filter[publication_date]"],
      message: "The start date must be on or before the end date.",
    });
  }

  const cursor = query["page[cursor]"];
  if (cursor && (cursor.field !== query.sort.field || cursor.direction !== query.sort.direction)) {
    context.addIssue({
      code: "custom",
      path: ["page[cursor]"],
      message: "The cursor does not match the requested sort.",
    });
  }
  if (cursor && cursor.filterKey !== documentFilterKey(
    query["filter[q]"],
    dateFrom,
    dateTo,
  )) {
    context.addIssue({
      code: "custom",
      path: ["page[cursor]"],
      message: "The cursor does not match the requested filters.",
    });
  }
}).transform((query) => ({
  q: query["filter[q]"],
  dateFrom: query["filter[publication_date][gte]"],
  dateTo: query["filter[publication_date][lte]"],
  sort: query.sort.field,
  direction: query.sort.direction,
  pageSize: query["page[size]"],
  cursor: query["page[cursor]"],
}));

export type DocumentQuery = z.output<typeof documentQuerySchema>;

export type ParsedDocumentQuery =
  | { ok: true; query: DocumentQuery }
  | { ok: false; parameter: string; detail: string };

export function documentFilterKey(q: string, dateFrom: string | null, dateTo: string | null): string {
  return JSON.stringify([q, dateFrom, dateTo]);
}

export function encodeCursor(cursor: DocumentCursor): string {
  return Buffer.from(JSON.stringify(cursor)).toString("base64url");
}

function invalidQuery(issue: { path: PropertyKey[]; message: string }): ParsedDocumentQuery {
  const parameter = issue.path[0];
  return {
    ok: false,
    parameter: typeof parameter === "string" ? parameter : "query",
    detail: issue.message,
  };
}

export function parseDocumentQuery(params: URLSearchParams): ParsedDocumentQuery {
  const filterParameters = supportedFilterParametersSchema.safeParse(Array.from(params.keys()));
  if (!filterParameters.success) return invalidQuery(filterParameters.error.issues[0]);

  const result = documentQuerySchema.safeParse({
    "filter[q]": params.get("filter[q]") ?? undefined,
    "filter[publication_date][gte]": params.get("filter[publication_date][gte]"),
    "filter[publication_date][lte]": params.get("filter[publication_date][lte]"),
    sort: params.get("sort") ?? undefined,
    "page[size]": params.get("page[size]") ?? undefined,
    "page[cursor]": params.get("page[cursor]") ?? undefined,
  });
  if (!result.success) return invalidQuery(result.error.issues[0]);

  return { ok: true, query: result.data };
}
