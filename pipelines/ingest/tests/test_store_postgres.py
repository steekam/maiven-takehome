from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from maiven_ingest.document_contract import DOCUMENT_FIELDS, JSONB_FIELDS, normalize_document
from maiven_ingest.models import ConcurrentRunError
from maiven_ingest.repository import PageCommit, PreparedDocument, RunReport
from maiven_ingest.store import UPSERT_DOCUMENT_SQL, IngestStore

from conftest import document


DATABASE_URL = os.environ.get("INGEST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set INGEST_TEST_DATABASE_URL to an isolated local PostgreSQL database",
)


def test_postgres_upsert_resume_checkpoint_and_atomic_rollback():
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        pytest.fail(
            "INGEST_TEST_DATABASE_URL must name an isolated database containing 'test'"
        )
    connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    store = IngestStore(connection)
    suffix = uuid.uuid4().hex
    identifiers = [
        f"ingest-test-{suffix}-{name}"
        for name in ("unrelated", "main", "continued", "rollback", "overflow")
    ]
    run_ids = []

    try:
        unrelated = normalize_document(document(identifiers[0], title="Keep this row"))
        with connection.cursor() as cursor:
            cursor.execute(UPSERT_DOCUMENT_SQL, _values(unrelated))

        initial_source = document(identifiers[1], title="Original title")
        first_row = PreparedDocument(normalize_document(initial_source), initial_source)
        fingerprint_one = f"integration-{suffix}-one"
        store.acquire_ingest_lock()
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as competing_connection:
            with pytest.raises(ConcurrentRunError):
                IngestStore(competing_connection).acquire_ingest_lock()
        first_run = store.start_or_resume_run(
            fingerprint=fingerprint_one,
            unique_target=2,
            initial_url="https://api.test/api/v1/documents.json?first=1",
            new_run=False,
        )
        run_ids.append(uuid.UUID(first_run.run_id))
        first_state = store.commit_page(
            PageCommit(
                run_id=first_run.run_id,
                request_id=str(uuid.uuid4()),
                page_number=1,
                fetched_at=datetime.now(UTC),
                http_status=200,
                upstream_request_id="upstream-one",
                archive_path="data/raw/federalregister/test/responses.jsonl",
                content_sha256="a" * 64,
                documents=(first_row, first_row),
                next_page_url="https://api.test/api/v1/documents.json?cursor=continue",
                source_records_seen=2,
                retry_count=0,
            )
        )
        assert first_state.status == "running"
        assert first_state.inserted_count == 1
        assert first_state.unique_documents_seen == 1
        store.mark_failed(first_run.run_id, "injected_restart", 0)
        store.release_ingest_lock()

        store.acquire_ingest_lock()
        resumed_run = store.start_or_resume_run(
            fingerprint=fingerprint_one,
            unique_target=2,
            initial_url="https://api.test/api/v1/documents.json?first=1",
            new_run=False,
        )
        assert resumed_run.run_id == first_run.run_id
        assert resumed_run.pages_fetched == 1
        assert resumed_run.next_page_url == "https://api.test/api/v1/documents.json?cursor=continue"
        continued_source = document(identifiers[2], title="Second page")
        continued_row = PreparedDocument(normalize_document(continued_source), continued_source)
        resumed_state = store.commit_page(
            PageCommit(
                run_id=resumed_run.run_id,
                request_id=str(uuid.uuid4()),
                page_number=2,
                fetched_at=datetime.now(UTC),
                http_status=200,
                upstream_request_id=None,
                archive_path="data/raw/federalregister/test/responses.jsonl",
                content_sha256="d" * 64,
                documents=(continued_row, first_row),
                next_page_url=None,
                source_records_seen=4,
                retry_count=0,
            )
        )
        store.release_ingest_lock()
        assert resumed_state.status == "succeeded"
        assert resumed_state.pages_fetched == 2
        assert resumed_state.inserted_count == 2
        report = store.report(resumed_run.run_id)
        assert isinstance(report, RunReport)
        assert report.state.unique_documents_seen == 2
        assert [page.page_number for page in report.pages] == [1, 2]
        assert all(isinstance(page.request_id, str) for page in report.pages)
        assert len(report.documents) == 2
        initial_hash = _source_sha256(initial_source)
        initial_link = next(
            link for link in report.documents if link.document_number == identifiers[1]
        )
        assert initial_link.source_sha256 == initial_hash

        changed_source = document(identifiers[1], title="Updated title")
        updated_row = PreparedDocument(normalize_document(changed_source), changed_source)
        fingerprint_two = f"integration-{suffix}-two"
        store.acquire_ingest_lock()
        second_run = store.start_or_resume_run(
            fingerprint=fingerprint_two,
            unique_target=1,
            initial_url="https://api.test/api/v1/documents.json?second=1",
            new_run=False,
        )
        run_ids.append(uuid.UUID(second_run.run_id))
        second_state = store.commit_page(
            PageCommit(
                run_id=second_run.run_id,
                request_id=str(uuid.uuid4()),
                page_number=1,
                fetched_at=datetime.now(UTC),
                http_status=200,
                upstream_request_id=None,
                archive_path="data/raw/federalregister/test/responses.jsonl",
                content_sha256="b" * 64,
                documents=(updated_row,),
                next_page_url=None,
                source_records_seen=1,
                retry_count=1,
            )
        )
        store.release_ingest_lock()
        assert second_state.status == "succeeded"
        assert second_state.inserted_count == 0
        assert second_state.updated_count == 1
        assert second_state.retries == 1
        changed_hash = _source_sha256(changed_source)
        second_report = store.report(second_run.run_id)
        changed_link = next(
            link for link in second_report.documents if link.document_number == identifiers[1]
        )
        assert changed_link.source_sha256 == changed_hash
        assert changed_hash != initial_hash

        rollback_source = document(identifiers[3], title="Should roll back")
        rollback_row = PreparedDocument(normalize_document(rollback_source), rollback_source)
        fingerprint_three = f"integration-{suffix}-three"
        store.acquire_ingest_lock()
        third_run = store.start_or_resume_run(
            fingerprint=fingerprint_three,
            unique_target=1,
            initial_url="https://api.test/api/v1/documents.json?third=1",
            new_run=False,
        )
        run_ids.append(uuid.UUID(third_run.run_id))
        with pytest.raises(psycopg.errors.CheckViolation):
            store.commit_page(
                PageCommit(
                    run_id=third_run.run_id,
                    request_id=str(uuid.uuid4()),
                    page_number=1,
                    fetched_at=datetime.now(UTC),
                    http_status=99,
                    upstream_request_id=None,
                    archive_path="data/raw/federalregister/test/responses.jsonl",
                    content_sha256="c" * 64,
                    documents=(rollback_row,),
                    next_page_url=None,
                    source_records_seen=1,
                    retry_count=0,
                )
            )

        third_state = store.state(third_run.run_id)
        assert third_state.status == "running"
        assert third_state.pages_fetched == 0
        assert third_state.next_page_url == third_run.next_page_url

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT title, agencies FROM documents WHERE document_number = %s",
                (identifiers[1],),
            )
            updated = cursor.fetchone()
            cursor.execute(
                "SELECT document_number FROM documents WHERE document_number = %s",
                (identifiers[0],),
            )
            retained = cursor.fetchone()
            cursor.execute(
                "SELECT document_number FROM documents WHERE document_number = %s",
                (identifiers[3],),
            )
            rolled_back = cursor.fetchone()
            cursor.execute(
                "SELECT source_sha256 FROM document_versions WHERE document_number = %s",
                (identifiers[3],),
            )
            rolled_back_version = cursor.fetchone()
        assert updated["title"] == "Updated title"
        assert updated["agencies"][0]["slug"] == "environmental-protection-agency"
        assert retained is not None
        assert rolled_back is None
        assert rolled_back_version is None
        store.mark_failed(third_run.run_id, "atomic_rollback_checked", 0)
        store.release_ingest_lock()

        fingerprint_four = f"integration-{suffix}-four"
        store.acquire_ingest_lock()
        fourth_run = store.start_or_resume_run(
            fingerprint=fingerprint_four,
            unique_target=1,
            initial_url="https://api.test/api/v1/documents.json?fourth=1",
            new_run=True,
        )
        run_ids.append(uuid.UUID(fourth_run.run_id))
        target_payload = document(identifiers[2], title="At target")
        overflow_payload = document(identifiers[4], title="Over target")
        target_state = store.commit_page(
            PageCommit(
                run_id=fourth_run.run_id,
                request_id=str(uuid.uuid4()),
                page_number=1,
                fetched_at=datetime.now(UTC),
                http_status=200,
                upstream_request_id=None,
                archive_path="data/raw/federalregister/test/responses.jsonl",
                content_sha256="e" * 64,
                documents=(
                    PreparedDocument(
                        normalize_document(target_payload),
                        target_payload,
                    ),
                    PreparedDocument(
                        normalize_document(overflow_payload),
                        overflow_payload,
                    ),
                ),
                next_page_url="https://api.test/api/v1/documents.json?cursor=over-target",
                source_records_seen=2,
                retry_count=0,
            )
        )
        store.release_ingest_lock()
        assert target_state.status == "succeeded"
        assert target_state.completion_reason == "target_reached"
        assert target_state.unique_documents_seen == 1
        assert len(store.report(fourth_run.run_id).documents) == 1
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT document_number FROM documents WHERE document_number = %s",
                (identifiers[4],),
            )
            overflow_row = cursor.fetchone()
            cursor.execute(
                "SELECT source_sha256 FROM document_versions WHERE document_number = %s",
                (identifiers[4],),
            )
            overflow_version = cursor.fetchone()
        assert overflow_row is None
        assert overflow_version is None

        fingerprint_five = f"integration-{suffix}-five"
        store.acquire_ingest_lock()
        fifth_run = store.start_or_resume_run(
            fingerprint=fingerprint_five,
            unique_target=2001,
            initial_url="https://api.test/api/v1/documents.json?fifth=1",
            new_run=True,
        )
        run_ids.append(uuid.UUID(fifth_run.run_id))
        source_limit_payload = document(identifiers[2], title="Source limit")
        source_limited_state = store.commit_page(
            PageCommit(
                run_id=fifth_run.run_id,
                request_id=str(uuid.uuid4()),
                page_number=1,
                fetched_at=datetime.now(UTC),
                http_status=200,
                upstream_request_id=None,
                archive_path="data/raw/federalregister/test/responses.jsonl",
                content_sha256="f" * 64,
                documents=(
                    PreparedDocument(
                        normalize_document(source_limit_payload),
                        source_limit_payload,
                    ),
                ),
                next_page_url="https://api.test/api/v1/documents.json?cursor=source-limit",
                source_records_seen=2000,
                retry_count=0,
            )
        )
        store.release_ingest_lock()
        assert source_limited_state.status == "partial"
        assert source_limited_state.next_page_url is None
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT source_sha256, source_payload FROM document_versions "
                "WHERE document_number = %s",
                (identifiers[1],),
            )
            versions = cursor.fetchall()
        assert {
            row["source_sha256"]: row["source_payload"] for row in versions
        } == {
            initial_hash: initial_source,
            changed_hash: changed_source,
        }
    finally:
        connection.rollback()
        with connection.transaction():
            with connection.cursor() as cursor:
                if run_ids:
                    cursor.execute(
                        "DELETE FROM ingest_runs WHERE run_id = ANY(%s)", (run_ids,)
                    )
                cursor.execute(
                    "DELETE FROM documents WHERE document_number = ANY(%s)", (identifiers,)
                )
        connection.close()


def _values(row):
    return [
        Jsonb(row[field]) if field in JSONB_FIELDS and row[field] is not None else row[field]
        for field in DOCUMENT_FIELDS
    ]


def _source_sha256(source_payload):
    canonical = json.dumps(
        source_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
