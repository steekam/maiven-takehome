export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type DocumentResource = {
  type: "documents";
  id: string;
  attributes: {
    document_number: string;
    title: string;
    type: string;
    publication_date: string;
    effective_on: string | null;
    signing_date: string | null;
    comments_close_on: string | null;
    abstract: string | null;
    action: string | null;
    agency_names: string[] | null;
    citation: string | null;
    docket_ids: string[] | null;
    cfr_references: JsonValue[] | null;
    html_url: string;
    pdf_url: string | null;
  };
};

export type DocumentPage = {
  jsonapi: { version: string };
  links: { self: string; next: string | null };
  data: DocumentResource[];
  meta: {
    request_id: string;
    page: { size: number; hasMore: boolean };
    ingest: {
      last_successful_at: string | null;
      latest_run: {
        status: string;
        completion_reason: string | null;
        started_at: string;
        finished_at: string | null;
      } | null;
    };
  };
};
