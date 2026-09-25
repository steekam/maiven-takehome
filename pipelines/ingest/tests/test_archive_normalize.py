from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maiven_ingest.archive import ResponseArchive, decode_archived_body
from maiven_ingest.fields import DOCUMENT_FIELDS, REQUIRED_FIELDS
from maiven_ingest.models import MalformedPayloadError, ResponseAttempt
from maiven_ingest.normalize import clean_text, normalize_document

def test_all_document_fields_match_the_openapi_snapshot_and_normalize(page_one):
    spec_path = Path(__file__).parents[1] / "spec" / "federal-register.openapi.json"
    spec = json.loads(spec_path.read_text())
    spec_fields = spec["components"]["schemas"]["DocumentField"]["items"]["enum"]
    source_document = page_one["results"][0]
    row = normalize_document(source_document)

    assert tuple(spec_fields) == DOCUMENT_FIELDS
    assert len(DOCUMENT_FIELDS) == 56
    assert set(row) == set(spec_fields)
    assert REQUIRED_FIELDS <= set(row)
    assert row["title"] == "EPA first rule"
    assert row["abstract"] == "First rule summary."
    assert row["agencies"] == source_document["agencies"]
    assert row["agencies"][0]["slug"] == "environmental-protection-agency"
    assert row["page_length"] == 0
    assert row["significant"] is False


def test_optional_source_properties_become_null_and_missing_agencies_default_to_array():
    row = normalize_document(
        {
            "document_number": "minimal-1",
            "title": "Minimal rule",
            "type": "RULE",
            "publication_date": "2026-09-24",
            "html_url": "https://example.test/minimal-1",
        }
    )
    assert row["agencies"] == []
    assert row["abstract"] is None
    assert len(row) == 56


def test_required_fields_and_typed_columns_fail_clearly(page_one):
    missing_number = page_one["results"][0] | {"document_number": None}
    with pytest.raises(MalformedPayloadError, match="empty document_number"):
        normalize_document(missing_number)

    invalid_date = page_one["results"][0] | {"publication_date": "2026-02-31"}
    with pytest.raises(MalformedPayloadError, match="publication_date"):
        normalize_document(invalid_date)

    invalid_page_length = page_one["results"][0] | {"page_length": True}
    with pytest.raises(MalformedPayloadError, match="page_length"):
        normalize_document(invalid_page_length)

    invalid_agencies = page_one["results"][0] | {"agencies": [{"slug": "epa"}, "bad"]}
    with pytest.raises(MalformedPayloadError, match="agencies"):
        normalize_document(invalid_agencies)


def test_clean_text_collapses_whitespace():
    assert clean_text("  one\n\t two   three  ") == "one two three"
    assert clean_text(" <p>One &amp; two</p> ") == "<p>One &amp; two</p>"


def test_archive_preserves_utf8_and_malformed_bytes_with_exact_hash(tmp_path):
    archive = ResponseArchive(tmp_path, "run-test")
    valid = b'{"results":["caf\xc3\xa9"]}'
    malformed = b'{"results":["caf\xff"]}'
    for request_id, body in (("request-1", valid), ("request-2", malformed)):
        archive.append(
            ResponseAttempt(
                run_id="run-test",
                request_id=request_id,
                page_number=1,
                attempt=1,
                fetched_at=datetime(2026, 9, 24, tzinfo=UTC),
                method="GET",
                requested_url="https://api.test/api/v1/documents.json?cursor=x",
                status_code=200,
                headers={"content-type": "application/json", "x-request-id": "up-1"},
                body=body,
            )
        )

    records = archive.read_records()
    assert [record["body_encoding"] for record in records] == ["utf-8", "base64"]
    assert [decode_archived_body(record) for record in records] == [valid, malformed]
    assert [record["content_sha256"] for record in records] == [
        hashlib.sha256(valid).hexdigest(),
        hashlib.sha256(malformed).hexdigest(),
    ]
    assert records[0]["response"]["upstream_request_id"] == "up-1"
    assert records[0]["request"]["method"] == "GET"


def test_archive_appends_attempts_and_recounts_only_committed_responses(tmp_path, page_one):
    archive = ResponseArchive(tmp_path, "run-test")
    for request_id, payload in (
        ("committed", page_one),
        ("not-committed", {"results": [{"document_number": "ignored"}]}),
    ):
        body = json.dumps(payload).encode()
        archive.append(
            ResponseAttempt(
                run_id="run-test",
                request_id=request_id,
                page_number=1,
                attempt=1,
                fetched_at=datetime(2026, 9, 24, tzinfo=UTC),
                method="GET",
                requested_url="https://api.test/api/v1/documents.json",
                status_code=200,
                headers={},
                body=body,
            )
        )
    assert archive.count_committed_source_records(["committed"]) == 1
    assert len(archive.read_records()) == 2


def test_unique_target_and_per_page_are_separate_cli_settings():
    from maiven_ingest.cli import build_parser

    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.max_unique_documents == 100
    assert defaults.per_page == 100
    changed = parser.parse_args(["--max-unique-documents", "7", "--per-page", "1"])
    assert changed.max_unique_documents == 7
    assert changed.per_page == 1
    with pytest.raises(SystemExit):
        parser.parse_args(["--max-unique-documents", "0"])
