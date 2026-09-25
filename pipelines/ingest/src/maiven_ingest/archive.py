from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from maiven_ingest.models import ArchiveReference, ResponseAttempt, TransportFailure


class RunEvidence:
    def __init__(self, repository_root: Path, run_id: str):
        self.repository_root = repository_root
        self.run_id = run_id
        self.directory = (
            repository_root
            / "data"
            / "raw"
            / "federalregister"
            / f"run_id={run_id}"
        )
        self.path = self.directory / "responses.jsonl"
        self.transport_failures_path = self.directory / "transport_failures.jsonl"

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.repository_root).as_posix()

    def record_response(self, attempt: ResponseAttempt) -> ArchiveReference:
        if attempt.run_id != self.run_id:
            raise ValueError("response attempt belongs to a different run")
        return self._append_response(attempt)

    def _append_response(self, attempt: ResponseAttempt) -> ArchiveReference:
        digest = hashlib.sha256(attempt.body).hexdigest()
        try:
            body = attempt.body.decode("utf-8", errors="strict")
            encoding = "utf-8"
        except UnicodeDecodeError:
            body = base64.b64encode(attempt.body).decode("ascii")
            encoding = "base64"

        record: dict[str, Any] = {
            "run_id": attempt.run_id,
            "request_id": attempt.request_id,
            "page": attempt.page_number,
            "attempt": attempt.attempt,
            "fetched_at": attempt.fetched_at.isoformat(),
            "request": {"method": attempt.method, "url": attempt.requested_url},
            "response": {
                "status": attempt.status_code,
                "upstream_request_id": attempt.headers.get("x-request-id"),
                "headers": attempt.headers,
                "body_complete": attempt.body_complete,
                "transport_error": attempt.transport_error,
            },
            "content_sha256": digest,
            "body_encoding": encoding,
            "body": body,
        }
        _append_jsonl(self.path, record)
        return ArchiveReference(self.relative_path, digest)

    def record_transport_failure(self, failure: TransportFailure) -> None:
        if failure.run_id != self.run_id:
            raise ValueError("transport failure belongs to a different run")
        _append_jsonl(
            self.transport_failures_path,
            {
                "run_id": failure.run_id,
                "request_id": failure.request_id,
                "page": failure.page_number,
                "attempt": failure.attempt,
                "requested_url": failure.requested_url,
                "error_class": failure.error_class,
                "error_message": failure.error_message,
            },
        )

    def read_records(self) -> list[dict[str, Any]]:
        return list(self.iter_records())

    def iter_records(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return
        self._truncate_incomplete_tail(self.path)
        with self.path.open("rb") as archive_file:
            for line_number, raw_line in enumerate(archive_file, start=1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(
                        f"invalid JSONL at {self.relative_path}:{line_number}"
                    ) from error
                if not isinstance(record, dict):
                    raise ValueError(
                        f"archive record must be an object at {self.relative_path}:{line_number}"
                    )
                if record.get("run_id") != self.run_id:
                    raise ValueError(
                        f"archive record belongs to a different run at {self.relative_path}:{line_number}"
                    )
                raw_body = decode_archived_body(record)
                actual_digest = hashlib.sha256(raw_body).hexdigest()
                if record.get("content_sha256") != actual_digest:
                    raise ValueError(
                        f"archive body hash mismatch at {self.relative_path}:{line_number}"
                    )
                yield record

    def _truncate_incomplete_tail(self, path: Path) -> None:
        with path.open("r+b") as archive_file:
            archive_file.seek(0, os.SEEK_END)
            size = archive_file.tell()
            if not size:
                return
            archive_file.seek(-1, os.SEEK_END)
            if archive_file.read(1) == b"\n":
                return
            end = size
            while end:
                start = max(0, end - 8192)
                archive_file.seek(start)
                block = archive_file.read(end - start)
                newline = block.rfind(b"\n")
                if newline >= 0:
                    archive_file.truncate(start + newline + 1)
                    archive_file.flush()
                    os.fsync(archive_file.fileno())
                    return
                end = start
            archive_file.truncate(0)
            archive_file.flush()
            os.fsync(archive_file.fileno())

    def iter_transport_failures(self) -> Iterable[dict[str, Any]]:
        path = self.transport_failures_path
        if not path.exists():
            return
        self._truncate_incomplete_tail(path)
        with path.open("rb") as failure_file:
            for line_number, raw_line in enumerate(failure_file, start=1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    relative_path = path.relative_to(self.repository_root).as_posix()
                    raise ValueError(
                        f"invalid JSONL at {relative_path}:{line_number}"
                    ) from error
                if not isinstance(record, dict) or record.get("run_id") != self.run_id:
                    relative_path = path.relative_to(self.repository_root).as_posix()
                    raise ValueError(
                        f"invalid transport failure record at {relative_path}:{line_number}"
                    )
                yield record

    def verify_committed_pages(self, pages: Iterable[Any]) -> int:
        expected_pages = {page.request_id: page for page in pages}
        if not expected_pages:
            return 0
        if not self.path.exists():
            raise ValueError(f"archive is missing for committed pages: {self.relative_path}")

        records_by_request: dict[str, list[dict[str, Any]]] = {}
        for record in self.iter_records():
            request_id = record.get("request_id")
            if request_id in expected_pages:
                records_by_request.setdefault(request_id, []).append(record)

        count = 0
        for request_id, page in expected_pages.items():
            matches = records_by_request.get(request_id, [])
            if len(matches) != 1:
                raise ValueError(
                    f"committed response {request_id} has {len(matches)} archive records"
                )
            record = matches[0]
            response = record.get("response")
            if (
                record.get("run_id") != self.run_id
                or record.get("page") != page.page_number
                or page.archive_path != self.relative_path
                or record.get("content_sha256") != page.content_sha256
                or not isinstance(response, dict)
                or response.get("status") != page.http_status
                or response.get("body_complete") is not True
            ):
                raise ValueError(f"committed response {request_id} does not match its manifest")
            raw_body = decode_archived_body(record)
            try:
                payload = json.loads(raw_body.decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"committed response {request_id} cannot be read") from error
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                raise ValueError(f"committed response {request_id} has no results array")
            count += len(results)
        return count

    def count_committed_source_records(self, request_ids: Iterable[str]) -> int:
        committed = set(request_ids)
        if not committed:
            return 0
        count = 0
        for record in self.iter_records():
            if record.get("request_id") not in committed:
                continue
            raw_body = decode_archived_body(record)
            try:
                payload = json.loads(raw_body.decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"committed response {record.get('request_id')} cannot be read"
                ) from error
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                raise ValueError(
                    f"committed response {record.get('request_id')} has no results array"
                )
            count += len(results)
        return count

    def attempt_manifest(
        self, pages: Iterable[Any], documents: Iterable[Any]
    ) -> list[dict[str, Any]]:
        committed_pages = {page.request_id: page for page in pages}
        links_by_request: dict[str, list[dict[str, Any]]] = {}
        for link in documents:
            links_by_request.setdefault(link.request_id, []).append(
                {
                    "document_number": link.document_number,
                    "outcome": link.outcome,
                    "source_sha256": link.source_sha256,
                }
            )

        attempts = []
        for record in self.iter_records():
            request_id = record["request_id"]
            response = record["response"]
            attempts.append(
                {
                    "request_id": request_id,
                    "page": record["page"],
                    "attempt": record["attempt"],
                    "requested_url": record["request"]["url"],
                    "status": response["status"],
                    "upstream_request_id": response.get("upstream_request_id"),
                    "archive_path": self.relative_path,
                    "content_sha256": record["content_sha256"],
                    "body_encoding": record["body_encoding"],
                    "body_complete": response.get("body_complete", True),
                    "transport_error": response.get("transport_error"),
                    "committed": request_id in committed_pages,
                    "documents": links_by_request.get(request_id, []),
                }
            )

        archived_request_ids = {attempt["request_id"] for attempt in attempts}
        for failure in self.iter_transport_failures():
            if failure["request_id"] in archived_request_ids:
                continue
            attempts.append(
                {
                    "request_id": failure["request_id"],
                    "page": failure["page"],
                    "attempt": failure["attempt"],
                    "requested_url": failure["requested_url"],
                    "status": None,
                    "upstream_request_id": None,
                    "archive_path": None,
                    "content_sha256": None,
                    "body_encoding": None,
                    "body_complete": False,
                    "transport_error": failure["error_class"],
                    "committed": False,
                    "documents": [],
                }
            )
        return attempts


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as file:
            file.write(encoded + b"\n")
            file.flush()
            os.fsync(file.fileno())
    finally:
        os.close(descriptor)


def decode_archived_body(record: dict[str, Any]) -> bytes:
    encoding = record.get("body_encoding")
    body = record.get("body")
    if not isinstance(body, str):
        raise ValueError("archive body must be a string")
    if encoding == "utf-8":
        return body.encode("utf-8")
    if encoding == "base64":
        try:
            return base64.b64decode(body, validate=True)
        except ValueError as error:
            raise ValueError("archive body contains invalid base64") from error
    raise ValueError(f"unknown archive body encoding: {encoding!r}")
