from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maiven_ingest.archive import RunEvidence
from maiven_ingest.document_contract import (
    DOCUMENT_FIELDS,
    TRANSFORM_VERSION,
    normalize_document,
)
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import (
    ArchiveReference,
    DocumentSearch,
    FetchedPage,
    IngestError,
    ResponseAttempt,
    TransportFailure,
)
from maiven_ingest.repository import (
    IngestRepository,
    PageCommit,
    PreparedDocument,
)


def epa_rules_search(
    *,
    per_page: int = 100,
    publication_date_gte: str | None = None,
    publication_date_lte: str | None = None,
) -> DocumentSearch:
    return DocumentSearch(
        agencies=("environmental-protection-agency",),
        document_types=("RULE",),
        per_page=per_page,
        order="newest",
        fields=DOCUMENT_FIELDS,
        publication_date_gte=publication_date_gte,
        publication_date_lte=publication_date_lte,
    )


class IngestWorkflow:
    def __init__(
        self,
        *,
        repository: IngestRepository,
        client: FederalRegisterClient,
        search: DocumentSearch,
        unique_target: int,
        repository_root: Path,
        logger: Any,
        new_run: bool = False,
    ):
        if unique_target <= 0:
            raise ValueError("max_unique_documents must be positive")
        self.repository = repository
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
        with self.repository.ingest_lock():
            return self._run_locked()

    def _run_locked(self) -> dict[str, Any]:
        state = self._start_run()
        error = self._process_run(state)
        summary = self._summary(state.run_id)
        self.logger.bind(event="run_summary", **summary).log(
            "ERROR" if error else "INFO", "run_summary"
        )
        return {"summary": summary, "error": _safe_error(error) if error else None}

    def _start_run(self) -> RunState:
        fingerprint = query_fingerprint(
            search=self.search,
            base_url=str(self.client.base_url),
            unique_target=self.unique_target,
        )
        state = self.repository.start_or_resume_run(
            fingerprint=fingerprint,
            unique_target=self.unique_target,
            initial_url=self.client.initial_url(self.search),
            new_run=self.new_run,
        )
        self.run_id = state.run_id
        self.evidence = RunEvidence(self.repository_root, state.run_id)
        self._log_run_started(state, fingerprint)
        return state

    def _log_run_started(self, state: RunState, fingerprint: str) -> None:
        self.logger.bind(
            event="run_started",
            run_id=state.run_id,
            query_fingerprint=fingerprint,
            unique_target=self.unique_target,
            pages_fetched=state.pages_fetched,
            unique_documents_seen=state.unique_documents_seen,
        ).info("run_started")

    def _process_run(self, state: RunState) -> Exception | None:
        try:
            self._advance_pages(state)
        except Exception as caught:
            self._record_run_failure(state, caught)
            return caught
        return None

    def _advance_pages(self, state: RunState) -> None:
        source_records_seen = self._verified_source_count(state)
        while state.next_page_url is not None:
            state, source_records_seen, fetched = self._commit_next_page(
                state, state.next_page_url, source_records_seen
            )
            self._log_page_committed(state, fetched)

    def _verified_source_count(self, state: RunState) -> int:
        pages = self.repository.committed_pages(state.run_id)
        return self._verify_source_count(state, pages)

    def _verify_source_count(
        self, state: RunState, pages: tuple[CommittedPage, ...]
    ) -> int:
        source_records_seen = self._evidence().verify_committed_pages(pages)
        if state.transform_version != "legacy" and source_records_seen != state.source_records_seen:
            raise ValueError("committed archive source count does not match the run checkpoint")
        return source_records_seen

    def _commit_next_page(
        self, state: RunState, page_url: str, source_records_seen: int
    ) -> tuple[RunState, int, FetchedPage]:
        self._active_page_number = state.pages_fetched + 1
        fetched = self.client.fetch_page(
            page_url,
            run_id=state.run_id,
            page_number=self._active_page_number,
            attempt_recorder=self,
        )
        self._active_retry_count = fetched.retries
        source_records_seen += len(fetched.page.results)
        state = self.repository.commit_page(
            self._page_commit(fetched, state.run_id, source_records_seen)
        )
        self._active_retry_count = 0
        self._active_page_number = None
        return state, source_records_seen, fetched

    @staticmethod
    def _page_commit(
        fetched: FetchedPage, run_id: str, source_records_seen: int
    ) -> PageCommit:
        documents = tuple(
            PreparedDocument(
                normalized=normalize_document(source_document),
                source_payload=source_document,
            )
            for source_document in fetched.page.results
        )
        return PageCommit(
            run_id=run_id,
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

    def _log_page_committed(self, state: RunState, fetched: FetchedPage) -> None:
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

    def _record_run_failure(self, state: RunState, error: Exception) -> None:
        retry_count = getattr(error, "retry_count", self._active_retry_count)
        failure_class = getattr(error, "failure_class", type(error).__name__)
        self.repository.mark_failed(state.run_id, failure_class, retry_count)
        self.logger.bind(
            event="run_failed",
            run_id=state.run_id,
            page=self._active_page_number,
            request_id=getattr(error, "request_id", None),
            archive_path=getattr(error, "archive_path", None),
            failure_class=failure_class,
            retry_count=retry_count,
        ).error("run_failed")

    def record_response(self, attempt: ResponseAttempt) -> ArchiveReference:
        reference = self._evidence().record_response(attempt)
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
        self._evidence().record_transport_failure(failure)
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
        evidence = self._evidence()
        report = self.repository.report(run_id)
        run = report.state
        pages = report.pages
        document_links = report.documents
        attempts = evidence.attempt_manifest(pages, document_links)
        failed_attempts = sum(not attempt["committed"] for attempt in attempts)
        source_records = self._verify_source_count(run, pages)
        ended_at = report.finished_at or datetime.now(UTC)
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
            "duration_seconds": max(0.0, (ended_at - report.started_at).total_seconds()),
            "archive_path": evidence.relative_path,
            "attempts": attempts,
            "page_manifest": _page_manifest(pages, document_links),
        }

    def _evidence(self) -> RunEvidence:
        if self.evidence is None:
            raise RuntimeError("run evidence is unavailable before a run starts")
        return self.evidence


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


def _page_manifest(
    pages: tuple[CommittedPage, ...], document_links: tuple[DocumentLink, ...]
) -> list[dict[str, Any]]:
    links_by_request: dict[str, list[DocumentLink]] = {}
    for link in document_links:
        links_by_request.setdefault(link.request_id, []).append(link)
    return [
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
                for link in links_by_request.get(page.request_id, ())
            ],
        }
        for page in pages
    ]


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
