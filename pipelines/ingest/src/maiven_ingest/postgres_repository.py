from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from psycopg import Connection
from psycopg.types.json import Jsonb

from maiven_ingest.document_contract import (
    DOCUMENT_FIELDS,
    JSONB_FIELDS,
    TRANSFORM_VERSION,
)
from maiven_ingest.models import (
    SOURCE_RESULT_LIMIT,
    ConcurrentRunError,
    FingerprintMismatchError,
)
from maiven_ingest.repository import (
    CommittedPage,
    DocumentLink,
    PageCommit,
    PreparedDocument,
    RunReport,
    RunState,
)


INSERT_COLUMNS = ", ".join(f'"{field}"' for field in DOCUMENT_FIELDS)
INSERT_VALUES = ", ".join(["%s"] * len(DOCUMENT_FIELDS))
UPDATE_COLUMNS = ", ".join(
    f'"{field}" = EXCLUDED."{field}"'
    for field in DOCUMENT_FIELDS
    if field != "document_number"
)
UPSERT_DOCUMENT_SQL = (
    f"INSERT INTO documents ({INSERT_COLUMNS}) VALUES ({INSERT_VALUES}) "
    'ON CONFLICT ("document_number") DO UPDATE SET '
    f"{UPDATE_COLUMNS}, \"updated_at\" = now() "
    "RETURNING (xmax = 0) AS inserted"
)


@dataclass(frozen=True, slots=True)
class _PageWrites:
    document_links: tuple[DocumentLink, ...]
    inserted_count: int
    updated_count: int


@dataclass(frozen=True, slots=True)
class _RunProgress:
    unique_count: int
    inserted_count: int
    updated_count: int
    completion_reason: str | None
    status: str
    checkpoint: str | None


class PostgresIngestRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def _acquire_ingest_lock(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock("
                "hashtextextended('federal-register-ingest', 0)) AS acquired"
            )
            acquired = cursor.fetchone()["acquired"]
        self.connection.commit()
        if not acquired:
            raise ConcurrentRunError(
                "another worker is already advancing a Federal Register ingest run"
            )

    @contextmanager
    def ingest_lock(self) -> Iterator[None]:
        self._acquire_ingest_lock()
        try:
            yield
        finally:
            self._release_ingest_lock()

    def _release_ingest_lock(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock("
                "hashtextextended('federal-register-ingest', 0)) AS released"
            )
        self.connection.commit()

    def start_or_resume_run(
        self,
        *,
        fingerprint: str,
        unique_target: int,
        initial_url: str,
        new_run: bool,
    ) -> RunState:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                incomplete = self._incomplete_runs(cursor)
                if new_run:
                    self._supersede_incomplete_runs(cursor)
                elif incomplete:
                    return self._resume_run(cursor, incomplete, fingerprint)
                return self._insert_run(cursor, fingerprint, unique_target, initial_url)

    @staticmethod
    def _incomplete_runs(cursor: Any) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT run_id, query_fingerprint, unique_target
            FROM ingest_runs
            WHERE status IN ('running', 'failed')
            ORDER BY started_at DESC, run_id DESC
            """
        )
        return cursor.fetchall()

    @staticmethod
    def _supersede_incomplete_runs(cursor: Any) -> None:
        cursor.execute(
            """
            UPDATE ingest_runs
            SET status = 'superseded', failure_class = 'superseded_by_new_run',
                next_page_url = NULL, finished_at = now()
            WHERE status IN ('running', 'failed')
            """
        )

    def _resume_run(
        self, cursor: Any, incomplete: list[dict[str, Any]], fingerprint: str
    ) -> RunState:
        if any(row["query_fingerprint"] != fingerprint for row in incomplete):
            raise FingerprintMismatchError(
                "an incomplete run has a different query fingerprint; use --new-run "
                "to start a separate run"
            )
        run_id = incomplete[0]["run_id"]
        self._supersede_duplicate_runs(cursor, run_id, fingerprint)
        cursor.execute(
            """
            UPDATE ingest_runs
            SET status = 'running', failure_class = NULL, finished_at = NULL
            WHERE run_id = %s
            RETURNING *
            """,
            (run_id,),
        )
        return _run_state(cursor.fetchone())

    @staticmethod
    def _supersede_duplicate_runs(cursor: Any, run_id: str, fingerprint: str) -> None:
        cursor.execute(
            """
            UPDATE ingest_runs
            SET status = 'superseded', failure_class = 'superseded_duplicate_run',
                next_page_url = NULL, finished_at = now()
            WHERE status IN ('running', 'failed') AND run_id <> %s
              AND query_fingerprint = %s
            """,
            (run_id, fingerprint),
        )

    @staticmethod
    def _insert_run(
        cursor: Any, fingerprint: str, unique_target: int, initial_url: str
    ) -> RunState:
        cursor.execute(
            """
            INSERT INTO ingest_runs (
                status, query_fingerprint, unique_target, next_page_url,
                transform_version
            ) VALUES ('running', %s, %s, %s, %s)
            RETURNING *
            """,
            (fingerprint, unique_target, initial_url, TRANSFORM_VERSION),
        )
        return _run_state(cursor.fetchone())

    def state(self, run_id: str) -> RunState:
        return _run_state(self._run_row(run_id))

    def _run_row(self, run_id: str) -> dict[str, Any]:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM ingest_runs WHERE run_id = %s", (run_id,))
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"ingest run {run_id} no longer exists")
        return row

    def commit_page(self, page: PageCommit) -> RunState:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                return self._commit_page(cursor, page)

    def _commit_page(self, cursor: Any, page: PageCommit) -> RunState:
        run = self._lock_page_run(cursor, page)
        seen = self._seen_document_numbers(cursor, page.run_id)
        accepted = self._select_page_documents(page.documents, seen, run["unique_target"])
        writes = self._upsert_page_documents(cursor, page, accepted)
        self._insert_page_manifest(cursor, page)
        self._insert_document_links(cursor, page.run_id, writes.document_links)
        return self._advance_run(cursor, run, page, writes)

    @staticmethod
    def _lock_page_run(cursor: Any, page: PageCommit) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT * FROM ingest_runs
            WHERE run_id = %s
            FOR UPDATE
            """,
            (page.run_id,),
        )
        run = cursor.fetchone()
        if run is None or run["status"] != "running":
            raise RuntimeError(f"ingest run {page.run_id} is not running")
        if page.page_number != run["pages_fetched"] + 1:
            raise RuntimeError("page number does not match the committed checkpoint")
        return run

    @staticmethod
    def _seen_document_numbers(cursor: Any, run_id: str) -> set[str]:
        cursor.execute(
            "SELECT document_number FROM ingest_run_documents WHERE run_id = %s",
            (run_id,),
        )
        return {row["document_number"] for row in cursor.fetchall()}

    @staticmethod
    def _select_page_documents(
        documents: tuple[PreparedDocument, ...],
        seen: set[str],
        unique_target: int,
    ) -> list[PreparedDocument]:
        accepted: list[PreparedDocument] = []
        accepted_numbers: set[str] = set()
        for prepared in documents:
            number = prepared.normalized["document_number"]
            if (
                number in seen
                or number in accepted_numbers
                or len(seen) + len(accepted) >= unique_target
            ):
                continue
            accepted.append(prepared)
            accepted_numbers.add(number)
        return accepted

    def _upsert_page_documents(
        self, cursor: Any, page: PageCommit, documents: list[PreparedDocument]
    ) -> _PageWrites:
        outcomes: list[DocumentLink] = []
        inserted_count = 0
        updated_count = 0
        for prepared in documents:
            outcome = self._upsert_document_and_version(cursor, page.request_id, prepared)
            outcomes.append(outcome)
            if outcome.outcome == "inserted":
                inserted_count += 1
            else:
                updated_count += 1
        return _PageWrites(tuple(outcomes), inserted_count, updated_count)

    @staticmethod
    def _upsert_document_and_version(
        cursor: Any, request_id: str, prepared: PreparedDocument
    ) -> DocumentLink:
        document = prepared.normalized
        outcome = PostgresIngestRepository._upsert_document(cursor, document)
        source_sha256 = _source_sha256(prepared.source_payload)
        PostgresIngestRepository._upsert_document_version(
            cursor, document["document_number"], source_sha256, prepared.source_payload
        )
        return DocumentLink(
            request_id=request_id,
            document_number=document["document_number"],
            outcome=outcome,
            source_sha256=source_sha256,
        )

    @staticmethod
    def _upsert_document(cursor: Any, document: dict[str, Any]) -> str:
        values = [
            Jsonb(document[field])
            if field in JSONB_FIELDS and document[field] is not None
            else document[field]
            for field in DOCUMENT_FIELDS
        ]
        cursor.execute(UPSERT_DOCUMENT_SQL, values)
        return "inserted" if cursor.fetchone()["inserted"] else "updated"

    @staticmethod
    def _upsert_document_version(
        cursor: Any,
        document_number: str,
        source_sha256: str,
        source_payload: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO document_versions (
                document_number, source_sha256, source_payload
            ) VALUES (%s, %s, %s)
            ON CONFLICT (document_number, source_sha256)
            DO UPDATE SET last_seen_at = now()
            """,
            (document_number, source_sha256, Jsonb(source_payload)),
        )

    @staticmethod
    def _insert_page_manifest(cursor: Any, page: PageCommit) -> None:
        cursor.execute(
            """
            INSERT INTO ingest_run_pages (
                request_id, run_id, page_number, fetched_at, http_status,
                upstream_request_id, archive_path, content_sha256
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                page.request_id,
                page.run_id,
                page.page_number,
                page.fetched_at,
                page.http_status,
                page.upstream_request_id,
                page.archive_path,
                page.content_sha256,
            ),
        )

    @staticmethod
    def _insert_document_links(
        cursor: Any, run_id: str, outcomes: tuple[DocumentLink, ...]
    ) -> None:
        for outcome in outcomes:
            cursor.execute(
                """
                INSERT INTO ingest_run_documents (
                    run_id, request_id, document_number, source_sha256, outcome
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    outcome.request_id,
                    outcome.document_number,
                    outcome.source_sha256,
                    outcome.outcome,
                ),
            )

    def _advance_run(
        self,
        cursor: Any,
        run: dict[str, Any],
        page: PageCommit,
        writes: _PageWrites,
    ) -> RunState:
        progress = _run_progress(run, page, writes)
        return self._save_run_progress(cursor, page, progress)

    @staticmethod
    def _save_run_progress(
        cursor: Any,
        page: PageCommit,
        progress: _RunProgress,
    ) -> RunState:
        cursor.execute(
            """
            UPDATE ingest_runs SET
                status = %s,
                completion_reason = %s,
                next_page_url = %s,
                pages_fetched = pages_fetched + 1,
                source_records_seen = %s,
                unique_documents_seen = %s,
                inserted_count = inserted_count + %s,
                updated_count = updated_count + %s,
                retries = retries + %s,
                failure_class = NULL,
                finished_at = CASE WHEN %s THEN now() ELSE NULL END
            WHERE run_id = %s
            RETURNING *
            """,
            (
                progress.status,
                progress.completion_reason,
                progress.checkpoint,
                page.source_records_seen,
                progress.unique_count,
                progress.inserted_count,
                progress.updated_count,
                page.retry_count,
                progress.completion_reason is not None,
                page.run_id,
            ),
        )
        return _run_state(cursor.fetchone())

    def mark_failed(self, run_id: str, failure_class: str, retry_count: int) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ingest_runs
                    SET status = 'failed', failure_class = %s,
                        retries = retries + %s, finished_at = now()
                    WHERE run_id = %s AND status = 'running'
                    """,
                    (failure_class, retry_count, run_id),
                )

    def committed_pages(self, run_id: str) -> tuple[CommittedPage, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, page_number, fetched_at, http_status,
                       upstream_request_id, archive_path, content_sha256
                FROM ingest_run_pages
                WHERE run_id = %s
                ORDER BY page_number
                """,
                (run_id,),
            )
            return tuple(_committed_page(row) for row in cursor.fetchall())

    def document_links(self, run_id: str) -> tuple[DocumentLink, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, document_number, outcome, source_sha256
                FROM ingest_run_documents
                WHERE run_id = %s
                ORDER BY request_id, document_number
                """,
                (run_id,),
            )
            return tuple(_document_link(row) for row in cursor.fetchall())

    def report(self, run_id: str) -> RunReport:
        run = self._run_row(run_id)
        return RunReport(
            state=_run_state(run),
            started_at=run["started_at"],
            finished_at=run["finished_at"],
            pages=self.committed_pages(run_id),
            documents=self.document_links(run_id),
        )


def _committed_page(row: dict[str, Any]) -> CommittedPage:
    return CommittedPage(
        request_id=str(row["request_id"]),
        page_number=row["page_number"],
        fetched_at=row["fetched_at"],
        http_status=row["http_status"],
        upstream_request_id=row["upstream_request_id"],
        archive_path=row["archive_path"],
        content_sha256=row["content_sha256"],
    )


def _source_sha256(source_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        source_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _completion_reason(
    run: dict[str, Any], page: PageCommit, unique_count: int
) -> str | None:
    if unique_count >= run["unique_target"]:
        return "target_reached"
    if page.source_records_seen >= SOURCE_RESULT_LIMIT:
        return "source_limit_reached"
    if page.next_page_url is None:
        return "source_exhausted"
    return None


def _completion_status(completion_reason: str | None) -> str:
    if completion_reason == "source_limit_reached":
        return "partial"
    return "succeeded" if completion_reason is not None else "running"


def _run_progress(
    run: dict[str, Any], page: PageCommit, writes: _PageWrites
) -> _RunProgress:
    unique_count = run["unique_documents_seen"] + len(writes.document_links)
    completion_reason = _completion_reason(run, page, unique_count)
    completed = completion_reason is not None
    return _RunProgress(
        unique_count=unique_count,
        inserted_count=writes.inserted_count,
        updated_count=writes.updated_count,
        completion_reason=completion_reason,
        status=_completion_status(completion_reason),
        checkpoint=None if completed else page.next_page_url,
    )


def _document_link(row: dict[str, Any]) -> DocumentLink:
    return DocumentLink(
        request_id=str(row["request_id"]),
        document_number=row["document_number"],
        outcome=row["outcome"],
        source_sha256=row["source_sha256"],
    )


def _run_state(row: dict[str, Any]) -> RunState:
    return RunState(
        run_id=str(row["run_id"]),
        status=row["status"],
        query_fingerprint=row["query_fingerprint"],
        unique_target=row["unique_target"],
        source_records_seen=row["source_records_seen"],
        transform_version=row["transform_version"],
        completion_reason=row["completion_reason"],
        next_page_url=row["next_page_url"],
        pages_fetched=row["pages_fetched"],
        unique_documents_seen=row["unique_documents_seen"],
        inserted_count=row["inserted_count"],
        updated_count=row["updated_count"],
        retries=row["retries"],
        failure_class=row["failure_class"],
    )
