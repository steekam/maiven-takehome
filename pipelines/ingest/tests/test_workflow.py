from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from maiven_ingest.config import ClientSettings
from maiven_ingest.diagnostics import configure_diagnostics
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import ConcurrentRunError, FingerprintMismatchError
from maiven_ingest.repository import CommittedPage, DocumentLink, RunReport, RunState
from maiven_ingest.sources.epa_rules import epa_rules_search
from maiven_ingest.workflow import IngestWorkflow, query_fingerprint

from conftest import document


BASE_URL = "https://api.test/api/v1/"
SECOND_PAGE = (
    "https://api.test/api/v1/documents.json?search_after_cursor=opaque%2Fcursor%2B1&per_page=100"
)


class PartialReadStream(httpx.SyncByteStream):
    def __init__(self, request):
        self.request = request

    def __iter__(self):
        yield b'{"results":'
        raise httpx.ReadTimeout("partial response", request=self.request)


class MemoryStore:
    """Small transactional store double for cursor and retry invariants."""

    def __init__(self, *, unrelated_document: str | None = "unrelated-existing"):
        self.runs = {}
        self.pages = {}
        self.links = {}
        self.documents = {unrelated_document: {"title": "keep me"}} if unrelated_document else {}
        self.locked = False
        self.run_sequence = 0

    def acquire_ingest_lock(self):
        if self.locked:
            raise ConcurrentRunError("already locked")
        self.locked = True

    def release_ingest_lock(self):
        self.locked = False

    def start_or_resume_run(self, *, fingerprint, unique_target, initial_url, new_run):
        incomplete = [
            run for run in self.runs.values() if run["status"] in {"running", "failed"}
        ]
        if incomplete and not new_run:
            if any(run["query_fingerprint"] != fingerprint for run in incomplete):
                raise FingerprintMismatchError("incomplete query fingerprint mismatch")
            run = max(incomplete, key=lambda item: item["started_at"])
            run["status"] = "running"
            run["failure_class"] = None
            run["finished_at"] = None
            return self._state(run)
        self.run_sequence += 1
        run_id = f"memory-run-{self.run_sequence}"
        self.runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "query_fingerprint": fingerprint,
            "unique_target": unique_target,
            "source_records_seen": 0,
            "transform_version": "2",
            "completion_reason": None,
            "next_page_url": initial_url,
            "pages_fetched": 0,
            "unique_documents_seen": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "retries": 0,
            "failure_class": None,
            "started_at": datetime.now(UTC),
            "finished_at": None,
        }
        self.pages[run_id] = []
        self.links[run_id] = []
        return self._state(self.runs[run_id])

    def committed_pages(self, run_id):
        return tuple(
            CommittedPage(
                request_id=str(page["request_id"]),
                page_number=page["page_number"],
                fetched_at=page["fetched_at"],
                http_status=page["http_status"],
                upstream_request_id=page["upstream_request_id"],
                archive_path=page["archive_path"],
                content_sha256=page["content_sha256"],
            )
            for page in self.pages[run_id]
        )

    def commit_page(
        self,
        *,
        run_id,
        request_id,
        page_number,
        fetched_at,
        http_status,
        upstream_request_id,
        archive_path,
        content_sha256,
        documents,
        source_documents=None,
        next_page_url,
        source_records_seen,
        retry_count,
    ):
        run = self.runs[run_id]
        assert run["status"] == "running"
        assert page_number == run["pages_fetched"] + 1
        seen = {link["document_number"] for link in self.links[run_id]}
        page_numbers = set()
        outcomes = []
        inserted = updated = 0
        for row in documents:
            number = row["document_number"]
            if (
                number in seen
                or number in page_numbers
                or len(seen) + len(page_numbers) >= run["unique_target"]
            ):
                continue
            page_numbers.add(number)
            outcome = "updated" if number in self.documents else "inserted"
            self.documents[number] = row
            outcomes.append({"request_id": request_id, "document_number": number, "outcome": outcome})
            inserted += outcome == "inserted"
            updated += outcome == "updated"
        self.pages[run_id].append(
            {
                "request_id": request_id,
                "page_number": page_number,
                "fetched_at": fetched_at,
                "http_status": http_status,
                "upstream_request_id": upstream_request_id,
                "archive_path": archive_path,
                "content_sha256": content_sha256,
            }
        )
        self.links[run_id].extend(outcomes)
        run["pages_fetched"] += 1
        run["unique_documents_seen"] += len(outcomes)
        run["inserted_count"] += inserted
        run["updated_count"] += updated
        run["retries"] += retry_count
        run["source_records_seen"] = source_records_seen
        if run["unique_documents_seen"] >= run["unique_target"]:
            run["completion_reason"] = "target_reached"
        elif source_records_seen >= 2000:
            run["completion_reason"] = "source_limit_reached"
        elif next_page_url is None:
            run["completion_reason"] = "source_exhausted"
        else:
            run["completion_reason"] = None
        complete = run["completion_reason"] is not None
        run["status"] = (
            "partial" if run["completion_reason"] == "source_limit_reached"
            else "succeeded" if complete
            else "running"
        )
        run["next_page_url"] = None if complete else next_page_url
        if complete:
            run["finished_at"] = datetime.now(UTC)
        return self._state(run)

    def mark_failed(self, run_id, failure_class, retry_count):
        run = self.runs[run_id]
        run["status"] = "failed"
        run["failure_class"] = failure_class
        run["retries"] += retry_count
        run["finished_at"] = datetime.now(UTC)

    def document_links(self, run_id):
        return tuple(
            DocumentLink(
                request_id=str(link["request_id"]),
                document_number=link["document_number"],
                outcome=link["outcome"],
            )
            for link in self.links[run_id]
        )

    def report(self, run_id):
        run = self.runs[run_id]
        return RunReport(
            state=self._state(run),
            started_at=run["started_at"],
            finished_at=run["finished_at"],
            pages=self.committed_pages(run_id),
            documents=self.document_links(run_id),
        )

    @staticmethod
    def _state(run):
        return RunState(
            run_id=run["run_id"],
            status=run["status"],
            query_fingerprint=run["query_fingerprint"],
            unique_target=run["unique_target"],
            source_records_seen=run["source_records_seen"],
            transform_version=run["transform_version"],
            completion_reason=run["completion_reason"],
            next_page_url=run["next_page_url"],
            pages_fetched=run["pages_fetched"],
            unique_documents_seen=run["unique_documents_seen"],
            inserted_count=run["inserted_count"],
            updated_count=run["updated_count"],
            retries=run["retries"],
            failure_class=run["failure_class"],
        )


def make_workflow(root, store, handler, *, target=100, retries=0, new_run=False):
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
    client = FederalRegisterClient(settings, http_client=http, sleeper=lambda _: None)
    logger = configure_diagnostics(root)
    workflow = IngestWorkflow(
        store=store,
        client=client,
        search=epa_rules_search(),
        unique_target=target,
        repository_root=root,
        diagnostics_path=root / "logs" / "ingest.jsonl",
        logger=logger,
        new_run=new_run,
    )
    return workflow, http


def fixture_page(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_unique_target_counts_distinct_ids_and_commits_only_remaining_allowance(
    tmp_path, page_one, page_two
):
    first = page_one["results"][0]
    second = page_two["results"][0]
    third = document("2026-00003")
    fourth = document("2026-00004")
    page_one["results"] = [first, second, copy.deepcopy(first)]
    page_two["results"] = [copy.deepcopy(second), third, fourth]
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=page_one if len(requests) == 1 else page_two, request=request)

    store = MemoryStore()
    workflow, http = make_workflow(tmp_path, store, handler, target=3)
    try:
        result = workflow.run()
    finally:
        http.close()

    summary = result["summary"]
    assert result["error"] is None
    assert summary["status"] == "succeeded"
    assert summary["unique_documents_seen"] == 3
    assert summary["inserted_records"] == 3
    assert summary["updated_records"] == 0
    assert summary["committed_pages"] == 2
    assert summary["committed_source_records_returned"] == 6
    assert store.documents["unrelated-existing"]["title"] == "keep me"
    assert [entry["page"] for entry in summary["attempts"]] == [1, 2]
    assert [link["document_number"] for link in summary["page_manifest"][1]["documents"]] == [
        "2026-00003"
    ]
    assert "opaque%2Fcursor%2B1" in requests[1]


def test_failed_page_resumes_from_last_committed_checkpoint_idempotently(
    tmp_path, page_one, page_two
):
    store = MemoryStore()
    page_two["results"] = [
        copy.deepcopy(page_one["results"][0]),
        page_two["results"][0],
    ]
    first_requests = []

    def first_handler(request):
        url = str(request.url)
        first_requests.append(url)
        if "search_after_cursor" not in url:
            return httpx.Response(200, json=page_one, request=request)
        status = 503 if len(first_requests) == 2 else 500
        return httpx.Response(status, content=b"temporary", request=request)

    first_workflow, first_http = make_workflow(
        tmp_path, store, first_handler, target=2, retries=1
    )
    try:
        failed = first_workflow.run()
    finally:
        first_http.close()
    failed_run = failed["summary"]["run_id"]
    assert failed["error"]
    assert failed["summary"]["status"] == "failed"
    assert failed["summary"]["committed_pages"] == 1
    assert failed["summary"]["retries"] == 1
    assert store.runs[failed_run]["next_page_url"] == SECOND_PAGE

    resume_requests = []

    def resume_handler(request):
        resume_requests.append(str(request.url))
        return httpx.Response(200, json=page_two, request=request)

    second_workflow, second_http = make_workflow(tmp_path, store, resume_handler, target=2)
    try:
        resumed = second_workflow.run()
    finally:
        second_http.close()

    summary = resumed["summary"]
    assert resumed["error"] is None
    assert summary["run_id"] == failed_run
    assert summary["status"] == "succeeded"
    assert summary["committed_pages"] == 2
    assert summary["unique_documents_seen"] == 2
    assert summary["inserted_records"] == 2
    assert summary["retries"] == 1
    assert summary["failures"] == 2
    assert len(resume_requests) == 1
    assert resume_requests[0] == SECOND_PAGE
    assert [page["page_number"] for page in summary["page_manifest"]] == [1, 2]
    assert len({link["document_number"] for link in store.links[failed_run]}) == 2
    assert store.documents["unrelated-existing"]["title"] == "keep me"

    archive_path = tmp_path / summary["archive_path"]
    archive_lines = [json.loads(line) for line in archive_path.read_text().splitlines()]
    assert len(archive_lines) == 4
    committed_ids = {
        page["request_id"] for page in summary["page_manifest"]
    }
    assert sum(record["request_id"] in committed_ids for record in archive_lines) == 2
    log_text = (tmp_path / "logs" / "ingest.jsonl").read_text()
    assert "EPA first rule" not in log_text
    assert "content_sha256" in log_text


def test_resume_fingerprint_mismatch_requires_explicit_new_run(tmp_path):
    store = MemoryStore()
    original = epa_rules_search()
    original_fingerprint = query_fingerprint(
        search=original, base_url=BASE_URL, unique_target=3
    )
    store.runs["existing"] = {
        "run_id": "existing",
        "status": "failed",
        "query_fingerprint": original_fingerprint,
        "unique_target": 3,
        "source_records_seen": 0,
        "transform_version": "2",
        "completion_reason": None,
        "next_page_url": "https://api.test/api/v1/documents.json?cursor=old",
        "pages_fetched": 0,
        "unique_documents_seen": 0,
        "inserted_count": 0,
        "updated_count": 0,
        "retries": 0,
        "failure_class": "temporary",
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
    }
    store.pages["existing"] = []
    store.links["existing"] = []
    changed = epa_rules_search(publication_date_gte="2026-09-01")

    def handler(request):
        return httpx.Response(200, json={"results": [], "next_page_url": None}, request=request)

    without_override, first_http = make_workflow(
        tmp_path, store, handler, target=3
    )
    without_override.search = changed
    with pytest.raises(FingerprintMismatchError):
        without_override.run()
    first_http.close()

    explicit, second_http = make_workflow(tmp_path, store, handler, target=3, new_run=True)
    explicit.search = changed
    try:
        result = explicit.run()
    finally:
        second_http.close()
    assert result["error"] is None
    assert result["summary"]["run_id"] != "existing"


def test_page_commit_stops_at_source_limit_even_when_next_link_exists(tmp_path):
    store = MemoryStore(unrelated_document=None)
    first_page = {
        "results": [document("at-limit")],
        "next_page_url": "https://api.test/api/v1/documents.json?cursor=after-limit",
    }

    def handler(request):
        return httpx.Response(200, json=first_page, request=request)

    workflow, http = make_workflow(tmp_path, store, handler, target=2001)
    original_commit = store.commit_page

    def source_limit_commit(**kwargs):
        kwargs["source_records_seen"] = 2000
        store.runs[kwargs["run_id"]]["transform_version"] = "legacy"
        return original_commit(**kwargs)

    store.commit_page = source_limit_commit
    try:
        result = workflow.run()
    finally:
        http.close()
    assert result["summary"]["status"] == "partial"
    assert result["summary"]["committed_pages"] == 1
    assert len(result["summary"]["attempts"]) == 1


def test_source_exhaustion_below_target_succeeds_and_deduplicates_partial_failure(tmp_path):
    store = MemoryStore(unrelated_document=None)
    terminal_page = {
        "results": [document("source-exhausted")],
        "next_page_url": None,
    }
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                stream=PartialReadStream(request),
                request=request,
            )
        return httpx.Response(200, json=terminal_page, request=request)

    workflow, http = make_workflow(tmp_path, store, handler, target=10, retries=1)
    try:
        result = workflow.run()
    finally:
        http.close()

    summary = result["summary"]
    assert result["error"] is None
    assert summary["status"] == "succeeded"
    assert summary["unique_documents_seen"] == 1
    assert summary["unique_documents_seen"] < summary["unique_target"]
    assert summary["committed_pages"] == 1
    assert summary["failures"] == 1
    assert len(summary["attempts"]) == 2
    assert summary["attempts"][0]["body_complete"] is False
    assert summary["attempts"][0]["transport_error"] == "ReadTimeout"
