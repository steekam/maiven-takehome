from __future__ import annotations

import json
import math
import time
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from maiven_ingest.config import ClientSettings
from maiven_ingest.models import (
    ArchiveReference,
    DocumentSearch,
    FetchedPage,
    MalformedPayloadError,
    Page,
    PermanentHttpError,
    ResponseArchiver,
    ResponseAttempt,
    ResponseTooLargeError,
    TransportFailure,
    TransportFailureHandler,
    TransientRequestError,
)


RETRYABLE_STATUSES = {408, 429}
SELECTED_HEADERS = {
    "content-encoding",
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "retry-after",
    "x-request-id",
}


def _url_origin(url: httpx.URL) -> tuple[str, str, int | None]:
    default_port = 443 if url.scheme == "https" else 80 if url.scheme == "http" else None
    return url.scheme.lower(), (url.host or "").lower(), url.port or default_port


class FederalRegisterClient:
    def __init__(
        self,
        settings: ClientSettings | None = None,
        *,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.settings = settings or ClientSettings()
        base_url = self.settings.base_url
        self.base_url = httpx.URL(base_url if base_url.endswith("/") else base_url + "/")
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(
            timeout=httpx.Timeout(
                connect=self.settings.connect_timeout_seconds,
                read=self.settings.read_timeout_seconds,
                write=self.settings.read_timeout_seconds,
                pool=self.settings.connect_timeout_seconds,
            ),
            follow_redirects=False,
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        self.sleeper = sleeper
        self.now = now

    def __enter__(self) -> FederalRegisterClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def initial_url(self, search: DocumentSearch) -> str:
        endpoint = self.base_url.join("documents.json")
        request = self.http.build_request("GET", endpoint, params=search.query_pairs())
        return str(request.url)

    def fetch_page(
        self,
        url: str,
        *,
        run_id: str,
        page_number: int,
        archive_response: ResponseArchiver,
        on_transport_failure: TransportFailureHandler,
    ) -> FetchedPage:
        self.validate_same_origin(url)
        last_request_id = ""
        last_archive_path: str | None = None
        last_status: int | None = None

        for attempt_number in range(1, self.settings.max_retries + 2):
            request_id = str(uuid.uuid4())
            last_request_id = request_id
            request = self.http.build_request("GET", url)
            try:
                response = self.http.send(request, stream=True)
            except httpx.TransportError as error:
                on_transport_failure(
                    TransportFailure(
                        run_id=run_id,
                        request_id=request_id,
                        page_number=page_number,
                        attempt=attempt_number,
                        requested_url=str(request.url),
                        error_class=type(error).__name__,
                        error_message=str(error),
                    )
                )
                if attempt_number > self.settings.max_retries:
                    raise TransientRequestError(
                        f"Federal Register request failed after {attempt_number} attempts: {type(error).__name__}",
                        retry_count=attempt_number - 1,
                        request_id=request_id,
                        archive_path=None,
                    ) from error
                self.sleeper(self._backoff_delay(attempt_number))
                continue

            body = bytearray()
            body_error: httpx.TransportError | None = None
            response_too_large = False
            if response.is_stream_consumed:
                chunk = response.content
                if len(chunk) > self.settings.max_response_bytes:
                    body.extend(chunk[: self.settings.max_response_bytes])
                    response_too_large = True
                else:
                    body.extend(chunk)
            else:
                try:
                    for chunk in response.iter_raw():
                        remaining = self.settings.max_response_bytes - len(body)
                        if len(chunk) > remaining:
                            body.extend(chunk[:remaining])
                            response_too_large = True
                            break
                        body.extend(chunk)
                except httpx.TransportError as error:
                    body_error = error

            fetched_at = self.now()
            status_code = response.status_code
            headers = self._selected_headers(response.headers)
            try:
                archive_reference = archive_response(
                    ResponseAttempt(
                        run_id=run_id,
                        request_id=request_id,
                        page_number=page_number,
                        attempt=attempt_number,
                        fetched_at=fetched_at,
                        method=request.method,
                        requested_url=str(request.url),
                        status_code=status_code,
                        headers=headers,
                        body=bytes(body),
                        body_complete=body_error is None and not response_too_large,
                        transport_error=(
                            type(body_error).__name__
                            if body_error
                            else "ResponseTooLargeError"
                            if response_too_large
                            else None
                        ),
                    )
                )
            finally:
                response.close()
            last_archive_path = archive_reference.archive_path
            last_status = status_code

            if body_error is not None:
                on_transport_failure(
                    TransportFailure(
                        run_id=run_id,
                        request_id=request_id,
                        page_number=page_number,
                        attempt=attempt_number,
                        requested_url=str(request.url),
                        error_class=type(body_error).__name__,
                        error_message=str(body_error),
                    )
                )

            if (
                not 200 <= status_code < 300
                and status_code not in RETRYABLE_STATUSES
                and status_code < 500
            ):
                error = PermanentHttpError(
                    status_code, request_id, archive_reference.archive_path
                )
                error.retry_count = attempt_number - 1
                raise error

            if response_too_large:
                error = ResponseTooLargeError(
                    self.settings.max_response_bytes,
                    request_id,
                    archive_reference.archive_path,
                )
                error.retry_count = attempt_number - 1
                raise error

            if body_error is not None:
                if attempt_number > self.settings.max_retries:
                    raise TransientRequestError(
                        f"Federal Register response body failed after {attempt_number} attempts: {type(body_error).__name__}",
                        retry_count=attempt_number - 1,
                        request_id=request_id,
                        archive_path=archive_reference.archive_path,
                        status_code=status_code,
                    ) from body_error
                delay = (
                    self._retry_after(headers.get("retry-after"), attempt_number)
                    if status_code in RETRYABLE_STATUSES or status_code >= 500
                    else self._backoff_delay(attempt_number)
                )
                self.sleeper(delay)
                continue

            if status_code in RETRYABLE_STATUSES or status_code >= 500:
                if attempt_number > self.settings.max_retries:
                    raise TransientRequestError(
                        f"Federal Register returned retryable HTTP {status_code} after {attempt_number} attempts",
                        retry_count=attempt_number - 1,
                        request_id=request_id,
                        archive_path=archive_reference.archive_path,
                        status_code=status_code,
                    )
                self.sleeper(
                    self._retry_after(headers.get("retry-after"), attempt_number)
                )
                continue

            try:
                page = self._decode_page(bytes(body))
                if page.next_page_url is not None:
                    self.validate_same_origin(page.next_page_url)
            except MalformedPayloadError as error:
                error.retry_count = attempt_number - 1
                error.request_id = request_id
                error.archive_path = archive_reference.archive_path
                raise
            return FetchedPage(
                page=page,
                request_id=request_id,
                page_number=page_number,
                status_code=status_code,
                fetched_at=fetched_at,
                upstream_request_id=headers.get("x-request-id"),
                archive_reference=archive_reference,
                retries=attempt_number - 1,
                attempts=attempt_number,
            )

        raise TransientRequestError(
            "Federal Register request exhausted its retry budget",
            retry_count=self.settings.max_retries,
            request_id=last_request_id,
            archive_path=last_archive_path,
            status_code=last_status,
        )

    def validate_same_origin(self, url: str) -> None:
        candidate = httpx.URL(url)
        if not candidate.is_absolute_url or _url_origin(candidate) != _url_origin(self.base_url):
            raise MalformedPayloadError("next_page_url must use the Federal Register API origin")
        if candidate.username or candidate.password:
            raise MalformedPayloadError("next_page_url cannot include credentials")

    def _decode_page(self, body: bytes) -> Page:
        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise MalformedPayloadError("Federal Register response is not valid UTF-8") from error
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise MalformedPayloadError("Federal Register response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise MalformedPayloadError("Federal Register response must be a JSON object")
        results = payload.get("results")
        if not isinstance(results, list):
            raise MalformedPayloadError("Federal Register page is missing a results array")
        if any(not isinstance(result, dict) for result in results):
            raise MalformedPayloadError("Federal Register results must contain document objects")
        next_page_url = payload.get("next_page_url")
        if next_page_url is not None and not isinstance(next_page_url, str):
            raise MalformedPayloadError("Federal Register next_page_url must be a URL or null")
        return Page(
            results=results,
            next_page_url=next_page_url,
            count=payload.get("count"),
            total_pages=payload.get("total_pages"),
        )

    @staticmethod
    def _selected_headers(headers: httpx.Headers) -> dict[str, str]:
        return {
            name: headers[name]
            for name in SELECTED_HEADERS
            if name in headers
        }

    def _backoff_delay(self, attempt_number: int) -> float:
        return min(
            self.settings.backoff_initial_seconds * 2 ** (attempt_number - 1),
            self.settings.backoff_max_seconds,
        )

    def _retry_after(self, value: str | None, attempt_number: int) -> float:
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - self.now()).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    return self._backoff_delay(attempt_number)
            if math.isfinite(delay):
                return min(max(0.0, delay), self.settings.retry_after_max_seconds)
        return self._backoff_delay(attempt_number)
