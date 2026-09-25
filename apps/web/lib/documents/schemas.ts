import { z } from "zod";
import { documentApiErrorCodes } from "./errors";

const jsonValueSchema = z.json();

export const documentResourceSchema = z.object({
  type: z.literal("documents"),
  id: z.string(),
  attributes: z.object({
    document_number: z.string(),
    title: z.string(),
    type: z.string(),
    publication_date: z.string(),
    effective_on: z.string().nullable(),
    signing_date: z.string().nullable(),
    comments_close_on: z.string().nullable(),
    abstract: z.string().nullable(),
    action: z.string().nullable(),
    agency_names: z.array(z.string()).nullable(),
    citation: z.string().nullable(),
    docket_ids: z.array(z.string()).nullable(),
    cfr_references: z.array(jsonValueSchema).nullable(),
    html_url: z.string(),
    pdf_url: z.string().nullable(),
  }),
});

export const documentPageSchema = z.object({
  jsonapi: z.object({ version: z.string() }),
  links: z.object({ self: z.string(), next: z.string().nullable() }),
  data: z.array(documentResourceSchema),
  meta: z.object({
    request_id: z.string(),
    page: z.object({ size: z.number(), hasMore: z.boolean() }),
    ingest: z.object({
      last_successful_at: z.string().nullable(),
      latest_run: z.object({
        status: z.string(),
        completion_reason: z.string().nullable(),
        started_at: z.string(),
        finished_at: z.string().nullable(),
      }).nullable(),
    }),
  }),
});

export const responseMetaSchema = z.object({
  meta: z.object({ request_id: z.string().optional() }).optional(),
});

export const documentApiErrorResponseSchema = responseMetaSchema.extend({
  errors: z.array(z.object({
    code: z.enum(documentApiErrorCodes),
    detail: z.string().optional(),
  })).min(1),
});

export type JsonValue = z.infer<typeof jsonValueSchema>;
export type DocumentResource = z.infer<typeof documentResourceSchema>;
export type DocumentPage = z.infer<typeof documentPageSchema>;
