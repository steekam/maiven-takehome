from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from maiven_ingest.config import ClientSettings
from maiven_ingest.fields import DOCUMENT_FIELDS
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import (
    ArchiveReference,
    MalformedPayloadError,
    PermanentHttpError,
    ResponseAttempt,
    TransportFailure,
)
from maiven_ingest.sources.epa_rules import epa_rules_search


FIXTURE_ROOT = Path(__file__).parent / "fixtures"
BASE_URL = "https://api.test/api/v1/"
RUN_ID = "00000000-0000-0000-0000-000000000001"


class PartialReadStream(httpx.SyncByteStream):
    def __init__(self, request):
        self.request = request

    def __iter__(self):
        yield b'{"results":'
        raise httpx.ReadTimeout("partial response", request=self.request)


def make_client(handler, *, retries=0, sleeps=None, now=None):
    settings = ClientSettings(
        base_url=BASE_URL,
        max_retries=retries,
        backoff_initial_seconds=1,
        backoff_max_seconds=8,
        user_agent="fixture-agent/1.0",
    )
    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    return FederalRegisterClient(
        settings,
        http_client=http,
        sleeper=(sleeps.append if sleeps is not None else lambda _: None),
        now=now or (lambda: datetime(2026, 9, 24, tzinfo=UTC)),
    )


class MemoryAttemptRecorder:
    def __init__(self, responses=None, transports=None):
        self.responses = responses if responses is not None else []
        self.transports = transports if transports is not None else []

    def record_response(self, attempt: ResponseAttempt) -> ArchiveReference:
        self.responses.append(attempt)
        return ArchiveReference(
            "data/raw/federalregister/test/responses.jsonl",
            "a" * 64,
        )

    def record_transport_failure(self, failure: TransportFailure) -> None:
        self.transports.append(failure)


def test_query_encodes_repeated_filters_dates_and_all_document_fields():
    client = make_client(lambda request: httpx.Response(200, json={"results": []}, request=request))
    url = client.initial_url(
        epa_rules_search(
            per_page=37,
            publication_date_gte="2026-01-01",
            publication_date_lte="2026-09-24",
        )
    )
    pairs = httpx.QueryParams(httpx.URL(url).query).multi_items()
    params = {}
    for key, value in pairs:
        params.setdefault(key, []).append(value)

    assert params["conditions[agencies][]"] == ["environmental-protection-agency"]
    assert params["conditions[type][]"] == ["RULE"]
    assert params["fields[]"] == list(DOCUMENT_FIELDS)
    assert params["per_page"] == ["37"]
    assert params["order"] == ["newest"]
    assert params["conditions[publication_date][gte]"] == ["2026-01-01"]
    assert params["conditions[publication_date][lte]"] == ["2026-09-24"]
    assert url.startswith(BASE_URL + "documents.json?")
    client.close()


def test_follows_next_page_link_verbatim_and_ignores_count_totals(page_one, page_two):
    first_url = "https://api.test/api/v1/documents.json?first=1"
    requested = []
    page_one["count"] = "wrong type is informational"
    page_one["total_pages"] = -1

    def handler(request):
        requested.append(str(request.url))
        if "first=1" in str(request.url):
            return httpx.Response(200, json=page_one, request=request)
        return httpx.Response(200, json=page_two, request=request)

    archived = []
    attempt_recorder = MemoryAttemptRecorder(archived)
    with make_client(handler) as client:
        first = client.fetch_page(
            first_url,
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )
        second = client.fetch_page(
            first.page.next_page_url,
            run_id=RUN_ID,
            page_number=2,
            attempt_recorder=attempt_recorder,
        )

    assert requested == [first_url, page_one["next_page_url"]]
    assert first.page.results[0]["document_number"] == "2026-00001"
    assert second.page.results[0]["document_number"] == "2026-00002"
    assert len(archived) == 2


def test_accepts_the_documented_per_page_one_twenty_result_anomaly():
    fixture = json.loads((FIXTURE_ROOT / "page-per-page-one-anomaly.json").read_text())
    fixture["next_page_url"] = None
    fixture["count"] = 1
    fixture["total_pages"] = 1
    payload = json.dumps(fixture).encode()
    attempt_recorder = MemoryAttemptRecorder()
    with make_client(
        lambda request: httpx.Response(200, content=payload, request=request)
    ) as client:
        page = client.fetch_page(
            client.initial_url(epa_rules_search(per_page=1)),
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )
    assert len(page.page.results) == 20


@pytest.mark.parametrize(
    ("status", "retry_after", "expected_sleep"),
    [(408, None, 1.0), (429, "7", 7.0), (503, None, 1.0)],
)
def test_retries_transient_statuses_after_archiving(
    status, retry_after, expected_sleep
):
    requests = []
    archived = []
    failures = []
    sleeps = []

    def handler(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            headers = {"Retry-After": retry_after} if retry_after else {}
            return httpx.Response(status, headers=headers, content=b"temporary", request=request)
        return httpx.Response(200, json={"results": []}, request=request)

    attempt_recorder = MemoryAttemptRecorder(archived, failures)
    with make_client(handler, retries=1, sleeps=sleeps) as client:
        page = client.fetch_page(
            "https://api.test/api/v1/documents.json",
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )
    assert page.retries == 1
    assert [attempt.status_code for attempt in archived] == [status, 200]
    assert sleeps == [expected_sleep]
    assert not failures


def test_partial_retryable_response_uses_retry_after_and_is_archived():
    archived = []
    failures = []
    sleeps = []
    attempt_recorder = MemoryAttemptRecorder(archived, failures)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7"},
                stream=PartialReadStream(request),
                request=request,
            )
        return httpx.Response(200, json={"results": []}, request=request)

    with make_client(handler, retries=1, sleeps=sleeps) as client:
        result = client.fetch_page(
            "https://api.test/api/v1/documents.json",
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )

    assert result.retries == 1
    assert sleeps == [7.0]
    assert archived[0].body == b'{"results":'
    assert archived[0].body_complete is False
    assert archived[0].transport_error == "ReadTimeout"
    assert failures[0].request_id == archived[0].request_id


def test_partial_permanent_response_fails_without_retry_after_archiving():
    archived = []
    failures = []
    sleeps = []
    attempt_recorder = MemoryAttemptRecorder(archived, failures)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            404,
            stream=PartialReadStream(request),
            request=request,
        )

    with make_client(handler, retries=1, sleeps=sleeps) as client:
        with pytest.raises(PermanentHttpError) as error:
            client.fetch_page(
                "https://api.test/api/v1/documents.json",
                run_id=RUN_ID,
                page_number=1,
                attempt_recorder=attempt_recorder,
            )

    assert calls == 1
    assert error.value.status_code == 404
    assert len(archived) == 1
    assert archived[0].body_complete is False
    assert archived[0].transport_error == "ReadTimeout"
    assert len(failures) == 1
    assert failures[0].request_id == archived[0].request_id
    assert sleeps == []


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_retries_connection_and_timeout_errors_without_response_archive(error_type):
    calls = []
    archived = []
    failures = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise error_type("temporary", request=request)
        return httpx.Response(200, json={"results": []}, request=request)

    attempt_recorder = MemoryAttemptRecorder(archived, failures)
    with make_client(handler, retries=1) as client:
        result = client.fetch_page(
            "https://api.test/api/v1/documents.json",
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )
    assert result.retries == 1
    assert len(archived) == 1
    assert len(failures) == 1
    assert failures[0].request_id != archived[0].request_id


def test_permanent_error_is_archived_before_it_is_raised():
    archived = []
    attempt_recorder = MemoryAttemptRecorder(archived)
    with make_client(
        lambda request: httpx.Response(404, content=b"missing", request=request)
    ) as client:
        with pytest.raises(PermanentHttpError) as error:
            client.fetch_page(
                "https://api.test/api/v1/documents.json",
                run_id=RUN_ID,
                page_number=1,
                attempt_recorder=attempt_recorder,
            )
    assert error.value.status_code == 404
    assert len(archived) == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"{not-json", "not valid JSON"),
        (b"{\"results\":[\xff]}", "not valid UTF-8"),
        (b"{\"count\": 2}", "missing a results array"),
    ],
)
def test_malformed_responses_are_archived_before_decode(body, message):
    archived = []
    attempt_recorder = MemoryAttemptRecorder(archived)
    with make_client(
        lambda request: httpx.Response(200, content=body, request=request)
    ) as client:
        with pytest.raises(MalformedPayloadError, match=message) as error:
            client.fetch_page(
                "https://api.test/api/v1/documents.json",
                run_id=RUN_ID,
                page_number=1,
                attempt_recorder=attempt_recorder,
            )
    assert len(archived) == 1
    assert error.value.archive_path.endswith("responses.jsonl")


def test_rejects_cross_origin_cursor_after_archiving_the_response():
    archived = []
    attempt_recorder = MemoryAttemptRecorder(archived)
    payload = {"results": [], "next_page_url": "https://evil.test/steal"}
    with make_client(
        lambda request: httpx.Response(200, json=payload, request=request)
    ) as client:
        with pytest.raises(MalformedPayloadError, match="origin"):
            client.fetch_page(
                "https://api.test/api/v1/documents.json",
                run_id=RUN_ID,
                page_number=1,
                attempt_recorder=attempt_recorder,
            )
    assert len(archived) == 1


def test_http_date_retry_after_is_respected():
    sleeps = []
    archived = []
    attempt_recorder = MemoryAttemptRecorder(archived)
    now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
    retry_date = "Thu, 24 Sep 2026 12:00:09 GMT"
    counter = 0

    def handler(request):
        nonlocal counter
        counter += 1
        if counter == 1:
            return httpx.Response(429, headers={"Retry-After": retry_date}, request=request)
        return httpx.Response(200, json={"results": []}, request=request)

    with make_client(handler, retries=1, sleeps=sleeps, now=lambda: now) as client:
        client.fetch_page(
            "https://api.test/api/v1/documents.json",
            run_id=RUN_ID,
            page_number=1,
            attempt_recorder=attempt_recorder,
        )
    assert sleeps == [9.0]
