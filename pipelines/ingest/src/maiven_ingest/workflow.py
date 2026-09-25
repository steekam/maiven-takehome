from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maiven_ingest.archive import RunEvidence
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import (
    ArchiveReference,
    DocumentSearch,
    IngestError,
    ResponseAttempt,
    TransportFailure,
)
from maiven_ingest.normalize import TRANSFORM_VERSION, normalize_document
from maiven_ingest.repository import (
    IngestRepository,
    PageCommit,
    PreparedDocument,
)


class IngestWorkflow:
    def __init__(
        self,
        *,
        store: IngestRepository,
        client: FederalRegisterClient,
        search: DocumentSearch,
        unique_target: int,
        repository_root: Path,
        logger: Any,
        new_run: bool = False,
    ):
        if unique_target <= 0:
            raise ValueError("max_unique_documents must be positive")
        self.store = store
        self.client = client
        self.search = search
        self.unique_target = unique_target
        self.repository_root = repository_root
        self.logger = logger
        self.new_run = new_run
        self.evidence: RunEvidence | None = None
        self.run_id: str | None = None
        self._active_retry_count = 0
        self._active_page_number: int | None = None

    def run(self) -> dict[str, Any]:
        self.store.acquire_ingest_lock()
        try:
            return self._run_locked()
        finally:
            self.store.release_ingest_lock()

    def _run_locked(self) -> dict[str, Any]:
        fingerprint = query_fingerprint(
            search=self.search,
            base_url=str(self.client.base_url),
            unique_target=self.unique_target,
        )
        initial_url = self.client.initial_url(self.search)
        state = self.store.start_or_resume_run(
            fingerprint=fingerprint,
            unique_target=self.unique_target,
            initial_url=initial_url,
            new_run=self.new_run,
        )
        self.run_id = state.run_id
        self.evidence = RunEvidence(self.repository_root, state.run_id)
        self.logger.bind(
            event="run_started",
            run_id=state.run_id,
            query_fingerprint=fingerprint,
            unique_target=self.unique_target,
            pages_fetched=state.pages_fetched,
            unique_documents_seen=state.unique_documents_seen,
        ).info("run_started")

        error: Exception | None = None
        try:
            committed_pages = self.store.committed_pages(state.run_id)
            source_records_seen = self.evidence.verify_committed_pages(committed_pages)
            if (
                state.transform_version != "legacy"
                and source_records_seen != state.source_records_seen
            ):
                raise ValueError("committed archive source count does not match the run checkpoint")
            while state.next_page_url is not None:
                self._active_page_number = state.pages_fetched + 1
                fetched = self.client.fetch_page(
                    state.next_page_url,
                    run_id=state.run_id,
                    page_number=self._active_page_number,
                    attempt_recorder=self,
                )
                self._active_retry_count = fetched.retries
                documents = tuple(
                    PreparedDocument(
                        normalized=normalize_document(source_document),
                        source_payload=source_document,
                    )
                    for source_document in fetched.page.results
                )
                source_records_seen += len(fetched.page.results)
                state = self.store.commit_page(
                    PageCommit(
                        run_id=state.run_id,
                        request_id=fetched.request_id,
                        page_number=fetched.page_number,
                        fetched_at=fetched.fetched_at,
                        http_status=fetched.status_code,
                        upstream_request_id=fetched.upstream_request_id,
                        archive_path=fetched.archive_reference.archive_path,
                        content_sha256=fetched.archive_reference.content_sha256,
                        documents=documents,
                        next_page_url=fetched.page.next_page_url,
                        source_records_seen=source_records_seen,
                        retry_count=fetched.retries,
                    )
                )
                self._active_retry_count = 0
                self._active_page_number = None
                self.logger.bind(
                    event="page_committed",
                    run_id=state.run_id,
                    request_id=fetched.request_id,
                    page=fetched.page_number,
                    archive_path=fetched.archive_reference.archive_path,
                    content_sha256=fetched.archive_reference.content_sha256,
                    returned_records=len(fetched.page.results),
                    unique_documents_seen=state.unique_documents_seen,
                    inserted_count=state.inserted_count,
                    updated_count=state.updated_count,
                    retry_count=fetched.retries,
                    status=state.status,
                ).info("page_committed")
        except Exception as caught:
            error = caught
            retry_count = getattr(caught, "retry_count", self._active_retry_count)
            failure_class = getattr(caught, "failure_class", type(caught).__name__)
            self.store.mark_failed(state.run_id, failure_class, retry_count)
            self.logger.bind(
                event="run_failed",
                run_id=state.run_id,
                page=self._active_page_number,
                request_id=getattr(caught, "request_id", None),
                archive_path=getattr(caught, "archive_path", None),
                failure_class=failure_class,
                retry_count=retry_count,
            ).error("run_failed")

        summary = self._summary(state.run_id)
        self.logger.bind(event="run_summary", **summary).log(
            "ERROR" if error else "INFO", "run_summary"
        )
        return {"summary": summary, "error": _safe_error(error) if error else None}

    def record_response(self, attempt: ResponseAttempt) -> ArchiveReference:
        if self.evidence is None:
            raise RuntimeError("run evidence is unavailable before a run starts")
        reference = self.evidence.record_response(attempt)
        self.logger.bind(
            event="http_response_archived",
            run_id=attempt.run_id,
            request_id=attempt.request_id,
            page=attempt.page_number,
            attempt=attempt.attempt,
            requested_url=attempt.requested_url,
            status=attempt.status_code,
            archive_path=reference.archive_path,
            content_sha256=reference.content_sha256,
            body_bytes=len(attempt.body),
            body_complete=attempt.body_complete,
        ).info("http_response_archived")
        return reference

    def record_transport_failure(self, failure: TransportFailure) -> None:
        if self.evidence is None:
            raise RuntimeError("run evidence is unavailable before a run starts")
        self.evidence.record_transport_failure(failure)
        self.logger.bind(
            event="http_transport_error",
            run_id=failure.run_id,
            request_id=failure.request_id,
            page=failure.page_number,
            attempt=failure.attempt,
            requested_url=failure.requested_url,
            error_class=failure.error_class,
            error=failure.error_message,
            archive_path=None,
        ).warning("http_transport_error")

    def _summary(self, run_id: str) -> dict[str, Any]:
        if self.evidence is None:
            raise RuntimeError("run evidence is unavailable before a run starts")
        report = self.store.report(run_id)
        run = report.state
        pages = report.pages
        document_links = report.documents
        attempts = self.evidence.attempt_manifest(pages, document_links)
        failed_attempts = sum(not attempt["committed"] for attempt in attempts)
        source_records = self.evidence.verify_committed_pages(pages)
        if run.transform_version != "legacy" and source_records != run.source_records_seen:
            raise ValueError("committed archive source count does not match the run checkpoint")
        ended_at = report.finished_at or datetime.now(UTC)
        started_at = report.started_at
        return {
            "run_id": run_id,
            "status": run.status,
            "query_fingerprint": run.query_fingerprint,
            "unique_target": run.unique_target,
            "target_reached": run.unique_documents_seen >= run.unique_target,
            "transform_version": run.transform_version,
            "completion_reason": run.completion_reason,
            "committed_pages": len(pages),
            "committed_source_records_returned": source_records,
            "source_records_seen": run.source_records_seen,
            "unique_documents_seen": run.unique_documents_seen,
            "inserted_records": run.inserted_count,
            "updated_records": run.updated_count,
            "retries": run.retries,
            "failures": failed_attempts,
            "failure_class": run.failure_class,
            "duration_seconds": max(0.0, (ended_at - started_at).total_seconds()),
            "archive_path": self.evidence.relative_path,
            "attempts": attempts,
            "page_manifest": [
                {
                    "request_id": page.request_id,
                    "page_number": page.page_number,
                    "fetched_at": _jsonable(page.fetched_at),
                    "http_status": page.http_status,
                    "upstream_request_id": page.upstream_request_id,
                    "archive_path": page.archive_path,
                    "content_sha256": page.content_sha256,
                    "documents": [
                        {
                            "document_number": link.document_number,
                            "outcome": link.outcome,
                            "source_sha256": link.source_sha256,
                        }
                        for link in document_links
                        if link.request_id == page.request_id
                    ],
                }
                for page in pages
            ],
        }


def query_fingerprint(
    *,
    search: DocumentSearch,
    base_url: str,
    unique_target: int,
    transform_version: str = TRANSFORM_VERSION,
) -> str:
    payload = {
        "base_url": base_url,
        "search": search.fingerprint_data(),
        "unique_target": unique_target,
        "transform_version": transform_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _safe_error(error: Exception) -> str:
    if isinstance(error, IngestError):
        return str(error)
    if type(error).__module__.startswith("psycopg"):
        return f"database operation failed ({type(error).__name__})"
    return type(error).__name__
