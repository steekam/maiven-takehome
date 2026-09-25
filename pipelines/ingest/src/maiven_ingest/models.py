from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


SOURCE_RESULT_LIMIT = 2000


class IngestError(Exception):
    failure_class = "ingest_error"


class MalformedPayloadError(IngestError):
    failure_class = "malformed_payload"


class ResponseTooLargeError(IngestError):
    failure_class = "response_too_large"

    def __init__(self, limit_bytes: int, request_id: str, archive_path: str):
        self.retry_count = 0
        self.request_id = request_id
        self.archive_path = archive_path
        super().__init__(f"Federal Register response exceeded the {limit_bytes}-byte limit")


class PermanentHttpError(IngestError):
    failure_class = "permanent_http_error"

    def __init__(self, status_code: int, request_id: str, archive_path: str):
        self.status_code = status_code
        self.request_id = request_id
        self.archive_path = archive_path
        super().__init__(f"Federal Register returned HTTP {status_code}")


class TransientRequestError(IngestError):
    failure_class = "transient_request_error"

    def __init__(
        self,
        message: str,
        *,
        retry_count: int,
        request_id: str,
        archive_path: str | None,
        status_code: int | None = None,
    ):
        self.retry_count = retry_count
        self.request_id = request_id
        self.archive_path = archive_path
        self.status_code = status_code
        super().__init__(message)


class ConcurrentRunError(IngestError):
    failure_class = "concurrent_run"


class FingerprintMismatchError(IngestError):
    failure_class = "query_fingerprint_mismatch"


@dataclass(frozen=True, slots=True)
class DocumentSearch:
    agencies: tuple[str, ...]
    document_types: tuple[str, ...]
    per_page: int = 100
    order: str = "newest"
    fields: tuple[str, ...] = ()
    publication_date_gte: str | None = None
    publication_date_lte: str | None = None
    term: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.per_page <= 1000:
            raise ValueError("per_page must be between 1 and 1000")
        if not self.agencies or not self.document_types:
            raise ValueError("at least one agency and document type are required")
        for value in (self.publication_date_gte, self.publication_date_lte):
            if value is not None:
                try:
                    if datetime.strptime(value, "%Y-%m-%d").date().isoformat() != value:
                        raise ValueError("publication date must use YYYY-MM-DD")
                except ValueError as error:
                    raise ValueError("publication date must use YYYY-MM-DD") from error
        if self.publication_date_gte and self.publication_date_lte:
            if self.publication_date_gte > self.publication_date_lte:
                raise ValueError("publication date lower bound is after upper bound")

    def query_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        pairs.extend(("conditions[agencies][]", slug) for slug in self.agencies)
        pairs.extend(("conditions[type][]", value) for value in self.document_types)
        pairs.extend(("fields[]", field) for field in self.fields)
        pairs.extend(
            [
                ("order", self.order),
                ("per_page", str(self.per_page)),
            ]
        )
        if self.term:
            pairs.append(("conditions[term]", self.term))
        if self.publication_date_gte:
            pairs.append(("conditions[publication_date][gte]", self.publication_date_gte))
        if self.publication_date_lte:
            pairs.append(("conditions[publication_date][lte]", self.publication_date_lte))
        return pairs

    def fingerprint_data(self) -> dict[str, Any]:
        return {
            "agencies": self.agencies,
            "document_types": self.document_types,
            "order": self.order,
            "per_page": self.per_page,
            "fields": self.fields,
            "publication_date_gte": self.publication_date_gte,
            "publication_date_lte": self.publication_date_lte,
            "term": self.term,
        }


@dataclass(frozen=True, slots=True)
class ResponseAttempt:
    run_id: str
    request_id: str
    page_number: int
    attempt: int
    fetched_at: datetime
    method: str
    requested_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    body_complete: bool = True
    transport_error: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveReference:
    archive_path: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class TransportFailure:
    run_id: str
    request_id: str
    page_number: int
    attempt: int
    requested_url: str
    error_class: str
    error_message: str


@dataclass(frozen=True, slots=True)
class Page:
    results: list[dict[str, Any]]
    next_page_url: str | None
    count: Any = None
    total_pages: Any = None


@dataclass(frozen=True, slots=True)
class FetchedPage:
    page: Page
    request_id: str
    page_number: int
    status_code: int
    fetched_at: datetime
    upstream_request_id: str | None
    archive_reference: ArchiveReference
    retries: int
    attempts: int


ResponseArchiver = Callable[[ResponseAttempt], ArchiveReference]
TransportFailureHandler = Callable[[TransportFailure], None]
