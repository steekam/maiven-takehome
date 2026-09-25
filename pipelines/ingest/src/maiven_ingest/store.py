from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from maiven_ingest.fields import DOCUMENT_FIELDS, JSONB_FIELDS
from maiven_ingest.models import (
    SOURCE_RESULT_LIMIT,
    ConcurrentRunError,
    FingerprintMismatchError,
)
from maiven_ingest.normalize import TRANSFORM_VERSION
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


class IngestStore:
    def __init__(self, connection: Connection):
        self.connection = connection

    def acquire_ingest_lock(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(hashtextextended('federal-register-ingest', 0)) AS acquired"
            )
            acquired = cursor.fetchone()["acquired"]
        self.connection.commit()
        if not acquired:
            raise ConcurrentRunError(
                "another worker is already advancing a Federal Register ingest run"
            )

    def release_ingest_lock(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended('federal-register-ingest', 0)) AS released"
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
                cursor.execute(
                    """
                    SELECT run_id, query_fingerprint, unique_target
                    FROM ingest_runs
                    WHERE status IN ('running', 'failed')
                    ORDER BY started_at DESC, run_id DESC
                    """
                )
                incomplete = cursor.fetchall()
                if new_run:
                    cursor.execute(
                        """
                        UPDATE ingest_runs
                        SET status = 'superseded', failure_class = 'superseded_by_new_run',
                            next_page_url = NULL, finished_at = now()
                        WHERE status IN ('running', 'failed')
                        """
                    )
                elif incomplete:
                    different = [
                        row for row in incomplete if row["query_fingerprint"] != fingerprint
                    ]
                    if different:
                        raise FingerprintMismatchError(
                            "an incomplete run has a different query fingerprint; use --new-run "
                            "to start a separate run"
                        )
                    run_id = incomplete[0]["run_id"]
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
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM ingest_runs WHERE run_id = %s", (run_id,))
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"ingest run {run_id} no longer exists")
        return _run_state(row)

    def commit_page(self, page: PageCommit) -> RunState:
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
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
                cursor.execute(
                    "SELECT document_number FROM ingest_run_documents WHERE run_id = %s",
                    (page.run_id,),
                )
                seen = {row["document_number"] for row in cursor.fetchall()}

                accepted: list[PreparedDocument] = []
                accepted_numbers: set[str] = set()
                for prepared in page.documents:
                    number = prepared.normalized["document_number"]
                    if (
                        number in seen
                        or number in accepted_numbers
                        or len(seen) + len(accepted) >= run["unique_target"]
                    ):
                        continue
                    accepted.append(prepared)
                    accepted_numbers.add(number)

                outcomes: list[tuple[str, str, str]] = []
                inserted_count = 0
                updated_count = 0
                for prepared in accepted:
                    document = prepared.normalized
                    values = []
                    for field in DOCUMENT_FIELDS:
                        value = document[field]
                        if field in JSONB_FIELDS and value is not None:
                            value = Jsonb(value)
                        values.append(value)
                    cursor.execute(UPSERT_DOCUMENT_SQL, values)
                    inserted = cursor.fetchone()["inserted"]
                    outcome = "inserted" if inserted else "updated"
                    document_number = document["document_number"]
                    source_payload = prepared.source_payload
                    source_canonical = json.dumps(
                        source_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8")
                    source_sha256 = hashlib.sha256(source_canonical).hexdigest()
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
                    outcomes.append((document_number, outcome, source_sha256))
                    if inserted:
                        inserted_count += 1
                    else:
                        updated_count += 1

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
                for document_number, outcome, source_sha256 in outcomes:
                    cursor.execute(
                        """
                        INSERT INTO ingest_run_documents (
                            run_id, request_id, document_number, source_sha256, outcome
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (page.run_id, page.request_id, document_number, source_sha256, outcome),
                    )

                unique_count = run["unique_documents_seen"] + len(outcomes)
                if unique_count >= run["unique_target"]:
                    completion_reason = "target_reached"
                elif page.source_records_seen >= SOURCE_RESULT_LIMIT:
                    completion_reason = "source_limit_reached"
                elif page.next_page_url is None:
                    completion_reason = "source_exhausted"
                else:
                    completion_reason = None
                completed = completion_reason is not None
                status = (
                    "partial" if completion_reason == "source_limit_reached"
                    else "succeeded" if completed
                    else "running"
                )
                checkpoint = None if completed else page.next_page_url
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
                        status,
                        completion_reason,
                        checkpoint,
                        page.source_records_seen,
                        unique_count,
                        inserted_count,
                        updated_count,
                        page.retry_count,
                        completed,
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
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT * FROM ingest_runs WHERE run_id = %s", (run_id,))
            run = cursor.fetchone()
        if run is None:
            raise RuntimeError(f"ingest run {run_id} no longer exists")
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
