ALTER TABLE "ingest_runs" DROP CONSTRAINT "ingest_runs_status_check";--> statement-breakpoint
ALTER TABLE "ingest_runs" DROP CONSTRAINT "ingest_runs_counters_check";--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD COLUMN "source_records_seen" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD COLUMN "transform_version" text DEFAULT 'legacy' NOT NULL;--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD COLUMN "completion_reason" text;--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD CONSTRAINT "ingest_runs_completion_reason_check" CHECK ("ingest_runs"."completion_reason" is null or "ingest_runs"."completion_reason" in ('target_reached', 'source_exhausted', 'source_limit_reached'));--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD CONSTRAINT "ingest_runs_status_check" CHECK ("ingest_runs"."status" in ('running', 'failed', 'succeeded', 'partial'));--> statement-breakpoint
ALTER TABLE "ingest_runs" ADD CONSTRAINT "ingest_runs_counters_check" CHECK ("ingest_runs"."pages_fetched" >= 0 and "ingest_runs"."unique_documents_seen" >= 0 and "ingest_runs"."inserted_count" >= 0 and "ingest_runs"."updated_count" >= 0 and "ingest_runs"."retries" >= 0 and "ingest_runs"."source_records_seen" >= 0);