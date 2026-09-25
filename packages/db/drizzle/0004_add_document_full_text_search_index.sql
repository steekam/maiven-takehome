CREATE INDEX IF NOT EXISTS "documents_search_idx" ON "documents" USING gin (to_tsvector('english', coalesce("title", '') || ' ' || coalesce("abstract", '')));
