from __future__ import annotations

import pytest

from maiven_ingest.postgres_repository import PostgresIngestRepository


class LockOnlyIngestRepository(PostgresIngestRepository):
    def __init__(self, acquire_error: Exception | None = None):
        self.events: list[str] = []
        self.acquire_error = acquire_error

    def _acquire_ingest_lock(self) -> None:
        self.events.append("acquired")
        if self.acquire_error is not None:
            raise self.acquire_error

    def _release_ingest_lock(self) -> None:
        self.events.append("released")


def test_ingest_lock_releases_after_body_failure():
    repository = LockOnlyIngestRepository()

    with pytest.raises(RuntimeError, match="body failed"):
        with repository.ingest_lock():
            raise RuntimeError("body failed")

    assert repository.events == ["acquired", "released"]


def test_ingest_lock_does_not_release_when_acquisition_fails():
    repository = LockOnlyIngestRepository(RuntimeError("lock busy"))

    with pytest.raises(RuntimeError, match="lock busy"):
        with repository.ingest_lock():
            pytest.fail("the lock body must not run")

    assert repository.events == ["acquired"]
