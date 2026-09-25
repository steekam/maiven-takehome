from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

import maiven_ingest.federal_register.client as federal_register_client
from maiven_ingest.archive import RunEvidence
from maiven_ingest.config import ClientSettings
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import ResponseAttempt
from maiven_ingest.document_contract import TRANSFORM_VERSION
from maiven_ingest.repository import (
    CommittedPage,
    DocumentLink,
    PageCommit,
    RunReport,
    RunState,
)
from maiven_ingest.workflow import IngestWorkflow, epa_rules_search


BASE_URL = "https://api.test/api/v1/"
RUN_ID = "test-run"
REQUEST_ID = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 9, 25, tzinfo=UTC)
INITIAL_URL = f"{BASE_URL}documents.json"


class NullLogger:
    def bind(self, **_fields):
        return self

    def info(self, *_args, **_fields):
        pass

    def warning(self, *_args, **_fields):
        pass

    def error(self, *_args, **_fields):
        pass

    def log(self, *_args, **_fields):
        pass


class ScriptedRepository:
    """Repository boundary stub; behavior comes from scripted responses."""

    def __init__(
        self,
        *,
        initial_state: RunState,
        commit_states: tuple[RunState, ...] = (),
        committed_page_data: tuple[CommittedPage, ...] = (),
        report_result: RunReport | None = None,
        start_error: Exception | None = None,
        report_error: Exception | None = None,
        mark_failed_error: Exception | None = None,
    ):
        self.initial_state = initial_state
        self.commit_states = iter(commit_states)
        self.committed_page_data = committed_page_data
        self.report_result = report_result
        self.start_error = start_error
        self.report_error = report_error
        self.mark_failed_error = mark_failed_error
        self.commit_pages: list[PageCommit] = []
        self.mark_failed_calls: list[tuple[str, str, int]] = []
        self.lock_events: list[str] = []

    @contextmanager
    def ingest_lock(self):
        self.lock_events.append("acquired")
        try:
            yield
        finally:
            self.lock_events.append("released")

    def start_or_resume_run(self, **_arguments) -> RunState:
        if self.start_error is not None:
            raise self.start_error
        return self.initial_state

    def committed_pages(self, _run_id: str) -> tuple[CommittedPage, ...]:
        return self.committed_page_data

    def commit_page(self, page: PageCommit) -> RunState:
        self.commit_pages.append(page)
        try:
            return next(self.commit_states)
        except StopIteration as error:
            raise AssertionError("unexpected page commit") from error

    def mark_failed(self, run_id: str, failure_class: str, retry_count: int) -> None:
        self.mark_failed_calls.append((run_id, failure_class, retry_count))
        if self.mark_failed_error is not None:
            raise self.mark_failed_error

    def report(self, _run_id: str) -> RunReport:
        if self.report_error is not None:
            raise self.report_error
        if self.report_result is None:
            raise AssertionError("no report was scripted")
        return self.report_result


def run_state(
    *,
    status: str,
    next_page_url: str | None,
    unique_target: int = 1,
    source_records_seen: int = 0,
    pages_fetched: int = 0,
    unique_documents_seen: int = 0,
    inserted_count: int = 0,
    updated_count: int = 0,
    retries: int = 0,
    completion_reason: str | None = None,
    failure_class: str | None = None,
) -> RunState:
    return RunState(
        run_id=RUN_ID,
        status=status,
        query_fingerprint="scripted-fingerprint",
        unique_target=unique_target,
        source_records_seen=source_records_seen,
        transform_version=TRANSFORM_VERSION,
        completion_reason=completion_reason,
        next_page_url=next_page_url,
        pages_fetched=pages_fetched,
        unique_documents_seen=unique_documents_seen,
        inserted_count=inserted_count,
        updated_count=updated_count,
        retries=retries,
        failure_class=failure_class,
    )


def make_workflow(root, repository, handler, *, monkeypatch, retries=0, target=1):
    settings = ClientSettings(
        base_url=BASE_URL,
        max_retries=retries,
        backoff_initial_seconds=0,
        backoff_max_seconds=0,
        user_agent="fixture-agent/1.0",
    )
    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": settings.user_agent, "Accept-Encoding": "identity"},
    )
    monkeypatch.setattr(
        federal_register_client.uuid,
        "uuid4",
        lambda: UUID(REQUEST_ID),
    )
    client = FederalRegisterClient(
        settings,
        http_client=http,
        sleeper=lambda _: None,
        now=lambda: NOW,
    )
    workflow = IngestWorkflow(
        repository=repository,
        client=client,
        search=epa_rules_search(),
        unique_target=target,
        repository_root=root,
        logger=NullLogger(),
    )
    return workflow, http


def test_workflow_pairs_normalized_document_with_original_source_payload(tmp_path, monkeypatch):
    source_document = {
        "document_number": "2026-00001",
        "title": "  EPA\tRule  ",
        "type": "RULE",
        "publication_date": "2026-09-20",
        "html_url": "https://example.test/documents/2026-00001",
        "agencies": [{"name": "Environmental Protection Agency"}],
        "source_extension": {"retained": True},
    }
    response_body = json.dumps(
        {"results": [source_document], "next_page_url": None},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    content_sha256 = hashlib.sha256(response_body).hexdigest()
    archive_path = f"data/raw/federalregister/run_id={RUN_ID}/responses.jsonl"
    state = run_state(
        status="succeeded",
        next_page_url=None,
        source_records_seen=1,
        pages_fetched=1,
        unique_documents_seen=1,
        inserted_count=1,
        completion_reason="target_reached",
    )
    repository = ScriptedRepository(
        initial_state=run_state(status="running", next_page_url=INITIAL_URL),
        commit_states=(state,),
        report_result=RunReport(
            state=state,
            started_at=NOW,
            finished_at=NOW,
            pages=(
                CommittedPage(
                    request_id=REQUEST_ID,
                    page_number=1,
                    fetched_at=NOW,
                    http_status=200,
                    upstream_request_id=None,
                    archive_path=archive_path,
                    content_sha256=content_sha256,
                ),
            ),
            documents=(
                DocumentLink(
                    request_id=REQUEST_ID,
                    document_number=source_document["document_number"],
                    outcome="inserted",
                    source_sha256="a" * 64,
                ),
            ),
        ),
    )

    def handler(request):
        return httpx.Response(
            200,
            content=response_body,
            headers={"content-type": "application/json"},
            request=request,
        )

    workflow, http = make_workflow(
        tmp_path, repository, handler, monkeypatch=monkeypatch
    )
    try:
        result = workflow.run()
    finally:
        http.close()

    assert result["error"] is None
    assert len(repository.commit_pages) == 1
    page = repository.commit_pages[0]
    assert isinstance(page, PageCommit)
    assert page.request_id == REQUEST_ID
    assert page.documents[0].normalized["title"] == "EPA Rule"
    assert page.documents[0].source_payload == source_document
    assert page.documents[0].source_payload["source_extension"] == {"retained": True}
    assert repository.lock_events == ["acquired", "released"]


def test_workflow_resumes_from_committed_run_evidence(tmp_path, monkeypatch):
    first_page_url = f"{BASE_URL}documents.json?first=1"
    next_page_url = f"{BASE_URL}documents.json?cursor=opaque"
    first_source = {
        "document_number": "2026-00001",
        "title": "First EPA rule",
        "type": "RULE",
        "publication_date": "2026-09-20",
        "html_url": "https://example.test/documents/2026-00001",
        "agencies": [],
    }
    first_body = json.dumps(
        {"results": [first_source], "next_page_url": next_page_url},
        separators=(",", ":"),
    ).encode()
    evidence = RunEvidence(tmp_path, RUN_ID)
    first_reference = evidence.record_response(
        ResponseAttempt(
            run_id=RUN_ID,
            request_id="00000000-0000-0000-0000-000000000002",
            page_number=1,
            attempt=1,
            fetched_at=NOW,
            method="GET",
            requested_url=first_page_url,
            status_code=200,
            headers={},
            body=first_body,
        )
    )
    first_page = CommittedPage(
        request_id="00000000-0000-0000-0000-000000000002",
        page_number=1,
        fetched_at=NOW,
        http_status=200,
        upstream_request_id=None,
        archive_path=first_reference.archive_path,
        content_sha256=first_reference.content_sha256,
    )
    second_source = {
        "document_number": "2026-00002",
        "title": "Second EPA rule",
        "type": "RULE",
        "publication_date": "2026-09-21",
        "html_url": "https://example.test/documents/2026-00002",
        "agencies": [],
    }
    second_body = json.dumps(
        {"results": [second_source], "next_page_url": None},
        separators=(",", ":"),
    ).encode()
    final_state = run_state(
        status="succeeded",
        next_page_url=None,
        unique_target=2,
        source_records_seen=2,
        pages_fetched=2,
        unique_documents_seen=2,
        inserted_count=2,
        completion_reason="target_reached",
    )
    repository = ScriptedRepository(
        initial_state=run_state(
            status="running",
            next_page_url=next_page_url,
            unique_target=2,
            source_records_seen=1,
            pages_fetched=1,
            unique_documents_seen=1,
            inserted_count=1,
        ),
        commit_states=(final_state,),
        committed_page_data=(first_page,),
        report_result=RunReport(
            state=final_state,
            started_at=NOW,
            finished_at=NOW,
            pages=(
                first_page,
                CommittedPage(
                    request_id=REQUEST_ID,
                    page_number=2,
                    fetched_at=NOW,
                    http_status=200,
                    upstream_request_id=None,
                    archive_path=first_reference.archive_path,
                    content_sha256=hashlib.sha256(second_body).hexdigest(),
                ),
            ),
            documents=(
                DocumentLink(
                    request_id=first_page.request_id,
                    document_number=first_source["document_number"],
                    outcome="inserted",
                    source_sha256="a" * 64,
                ),
                DocumentLink(
                    request_id=REQUEST_ID,
                    document_number=second_source["document_number"],
                    outcome="inserted",
                    source_sha256="b" * 64,
                ),
            ),
        ),
    )

    def handler(request):
        assert str(request.url) == next_page_url
        return httpx.Response(
            200,
            content=second_body,
            headers={"content-type": "application/json"},
            request=request,
        )

    workflow, http = make_workflow(
        tmp_path, repository, handler, monkeypatch=monkeypatch, target=2
    )
    try:
        result = workflow.run()
    finally:
        http.close()

    assert result["error"] is None
    assert len(repository.commit_pages) == 1
    assert repository.commit_pages[0].page_number == 2
    assert repository.commit_pages[0].source_records_seen == 2
    assert result["summary"]["committed_pages"] == 2
    assert all(attempt["committed"] for attempt in result["summary"]["attempts"])


def test_transport_failure_is_reported_from_durable_evidence_without_logs(tmp_path, monkeypatch):
    state = run_state(
        status="failed",
        next_page_url=INITIAL_URL,
        failure_class="transient_request_error",
    )
    repository = ScriptedRepository(
        initial_state=run_state(status="running", next_page_url=INITIAL_URL),
        report_result=RunReport(
            state=state,
            started_at=NOW,
            finished_at=NOW,
            pages=(),
            documents=(),
        ),
    )

    def handler(request):
        raise httpx.ConnectError("network unavailable", request=request)

    workflow, http = make_workflow(
        tmp_path, repository, handler, monkeypatch=monkeypatch
    )
    try:
        result = workflow.run()
    finally:
        http.close()

    attempt, = result["summary"]["attempts"]
    assert result["summary"]["failures"] == 1
    assert attempt["request_id"] == REQUEST_ID
    assert attempt["transport_error"] == "ConnectError"
    assert attempt["committed"] is False
    evidence_path = (
        tmp_path
        / "data/raw/federalregister"
        / f"run_id={RUN_ID}"
        / "transport_failures.jsonl"
    )
    record, = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    assert record["error_class"] == "ConnectError"
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("failure_point", ["start_or_resume", "mark_failed", "summary"])
def test_lock_is_released_if_post_acquire_work_raises(
    tmp_path, monkeypatch, failure_point
):
    failure = RuntimeError(f"{failure_point} failed")
    commit_state = run_state(
        status="succeeded",
        next_page_url=None,
        completion_reason="source_exhausted",
        pages_fetched=1,
    )
    repository = ScriptedRepository(
        initial_state=run_state(status="running", next_page_url=INITIAL_URL),
        commit_states=(commit_state,),
        start_error=failure if failure_point == "start_or_resume" else None,
        report_error=failure if failure_point == "summary" else None,
        mark_failed_error=failure if failure_point == "mark_failed" else None,
    )

    def handler(request):
        if failure_point == "mark_failed":
            raise httpx.ConnectError("network unavailable", request=request)
        return httpx.Response(
            200,
            json={"results": [], "next_page_url": None},
            request=request,
        )

    workflow, http = make_workflow(
        tmp_path, repository, handler, monkeypatch=monkeypatch
    )
    try:
        with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
            workflow.run()
    finally:
        http.close()

    assert repository.lock_events == ["acquired", "released"]
