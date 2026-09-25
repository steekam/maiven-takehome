CREATE TABLE "document_versions" (
	"document_number" text NOT NULL,
	"source_sha256" text NOT NULL,
	"source_payload" jsonb NOT NULL,
	"first_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "document_versions_document_sha256_unique" UNIQUE("document_number","source_sha256")
);
--> statement-breakpoint
ALTER TABLE "ingest_runs" DROP CONSTRAINT "ingest_runs_status_check";--> statement-breakpoint
ALTER TABLE "ingest_run_documents" ADD COLUMN "source_sha256" text;--> statement-breakpoint
ALTER TABLE "document_versions" ADD CONSTRAINT "document_versions_document_number_documents_document_number_fk" FOREIGN KEY ("document_number") REFERENCES "public"."documents"("document_number") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ingest_run_documents" ADD CONSTRAINT "ingest_run_documents_version_fk" FOREIGN KEY ("document_number","source_sha256") REFERENCES "public"."document_versions"("document_number","source_sha256") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD CONSTRAINT "ingest_runs_status_check" CHECK ("ingest_runs"."status" in ('running', 'failed', 'succeeded', 'partial', 'superseded'));