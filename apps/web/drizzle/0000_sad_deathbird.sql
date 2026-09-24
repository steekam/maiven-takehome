CREATE TABLE "documents" (
	"document_number" text PRIMARY KEY NOT NULL,
	"title" text NOT NULL,
	"publication_date" date NOT NULL,
	"effective_on" date,
	"abstract" text,
	"agencies" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"html_url" text NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ingest_run_documents" (
	"run_id" uuid NOT NULL,
	"request_id" uuid NOT NULL,
	"document_number" text NOT NULL,
	"outcome" text NOT NULL,
	CONSTRAINT "ingest_run_documents_run_id_document_number_pk" PRIMARY KEY("run_id","document_number"),
	CONSTRAINT "ingest_run_documents_outcome_check" CHECK ("ingest_run_documents"."outcome" in ('inserted', 'updated'))
);
--> statement-breakpoint
CREATE TABLE "ingest_run_pages" (
	"request_id" uuid PRIMARY KEY NOT NULL,
	"run_id" uuid NOT NULL,
	"page_number" integer NOT NULL,
	"fetched_at" timestamp with time zone NOT NULL,
	"http_status" integer NOT NULL,
	"upstream_request_id" text,
	"archive_path" text NOT NULL,
	"content_sha256" text NOT NULL,
	CONSTRAINT "ingest_run_pages_run_request_unique" UNIQUE("run_id","request_id"),
	CONSTRAINT "ingest_run_pages_run_page_unique" UNIQUE("run_id","page_number"),
	CONSTRAINT "ingest_run_pages_page_number_check" CHECK ("ingest_run_pages"."page_number" > 0),
	CONSTRAINT "ingest_run_pages_http_status_check" CHECK ("ingest_run_pages"."http_status" between 100 and 599),
	CONSTRAINT "ingest_run_pages_sha256_check" CHECK ("ingest_run_pages"."content_sha256" ~ '^[0-9a-f]{64}$')
);
--> statement-breakpoint
CREATE TABLE "ingest_runs" (
	"run_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"status" text DEFAULT 'running' NOT NULL,
	"query_fingerprint" text NOT NULL,
	"unique_target" integer DEFAULT 100 NOT NULL,
	"next_page_url" text,
	"pages_fetched" integer DEFAULT 0 NOT NULL,
	"unique_documents_seen" integer DEFAULT 0 NOT NULL,
	"inserted_count" integer DEFAULT 0 NOT NULL,
	"updated_count" integer DEFAULT 0 NOT NULL,
	"retries" integer DEFAULT 0 NOT NULL,
	"failure_class" text,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"finished_at" timestamp with time zone,
	CONSTRAINT "ingest_runs_status_check" CHECK ("ingest_runs"."status" in ('running', 'failed', 'succeeded')),
	CONSTRAINT "ingest_runs_unique_target_check" CHECK ("ingest_runs"."unique_target" > 0),
	CONSTRAINT "ingest_runs_counters_check" CHECK ("ingest_runs"."pages_fetched" >= 0 and "ingest_runs"."unique_documents_seen" >= 0 and "ingest_runs"."inserted_count" >= 0 and "ingest_runs"."updated_count" >= 0 and "ingest_runs"."retries" >= 0)
);
--> statement-breakpoint
ALTER TABLE "ingest_run_documents" ADD CONSTRAINT "ingest_run_documents_document_number_documents_document_number_fk" FOREIGN KEY ("document_number") REFERENCES "public"."documents"("document_number") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ingest_run_documents" ADD CONSTRAINT "ingest_run_documents_page_fk" FOREIGN KEY ("run_id","request_id") REFERENCES "public"."ingest_run_pages"("run_id","request_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ingest_run_pages" ADD CONSTRAINT "ingest_run_pages_run_id_ingest_runs_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."ingest_runs"("run_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "documents_publication_cursor_idx" ON "documents" USING btree ("publication_date" DESC NULLS LAST,"document_number" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "ingest_run_documents_request_idx" ON "ingest_run_documents" USING btree ("request_id");