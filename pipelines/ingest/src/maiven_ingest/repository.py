from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RunState:
    run_id: str
    status: str
    query_fingerprint: str
    unique_target: int
    source_records_seen: int
    transform_version: str
    completion_reason: str | None
    next_page_url: str | None
    pages_fetched: int
    unique_documents_seen: int
    inserted_count: int
    updated_count: int
    retries: int
    failure_class: str | None


@dataclass(frozen=True, slots=True)
class CommittedPage:
    request_id: str
    page_number: int
    fetched_at: datetime
    http_status: int
    upstream_request_id: str | None
    archive_path: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class DocumentLink:
    request_id: str
    document_number: str
    outcome: str
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RunReport:
    state: RunState
    started_at: datetime
    finished_at: datetime | None
    pages: tuple[CommittedPage, ...]
    documents: tuple[DocumentLink, ...]


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    normalized: dict[str, Any]
    source_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.normalized["document_number"] != self.source_payload["document_number"]:
            raise ValueError("normalized and source documents must have the same document_number")


@dataclass(frozen=True, slots=True)
class PageCommit:
    run_id: str
    request_id: str
    page_number: int
    fetched_at: datetime
    http_status: int
    upstream_request_id: str | None
    archive_path: str
    content_sha256: str
    documents: tuple[PreparedDocument, ...]
    next_page_url: str | None
    source_records_seen: int
    retry_count: int


class IngestRepository(Protocol):
    def acquire_ingest_lock(self) -> None: ...

    def release_ingest_lock(self) -> None: ...

    def start_or_resume_run(
        self,
        *,
        fingerprint: str,
        unique_target: int,
        initial_url: str,
        new_run: bool,
    ) -> RunState: ...

    def committed_pages(self, run_id: str) -> tuple[CommittedPage, ...]: ...

    def commit_page(self, page: PageCommit) -> RunState:
        """Atomically persist one page and its run checkpoint."""
        ...

    def mark_failed(self, run_id: str, failure_class: str, retry_count: int) -> None: ...

    def report(self, run_id: str) -> RunReport: ...
