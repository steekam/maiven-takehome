from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def repository_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pipelines" / "ingest").is_dir():
            return candidate
    raise RuntimeError("could not locate repository root")


@dataclass(frozen=True, slots=True)
class ClientSettings:
    base_url: str = "https://www.federalregister.gov/api/v1/"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    retry_after_max_seconds: float = 60.0
    max_response_bytes: int = 33_554_432
    user_agent: str = "maiven-takehome-ingest/0.1"

    @classmethod
    def from_env(cls) -> ClientSettings:
        return cls(
            base_url=os.environ.get(
                "FEDERAL_REGISTER_API_BASE_URL", "https://www.federalregister.gov/api/v1/"
            ),
            connect_timeout_seconds=float(
                os.environ.get("FEDERAL_REGISTER_CONNECT_TIMEOUT", "5")
            ),
            read_timeout_seconds=float(
                os.environ.get("FEDERAL_REGISTER_READ_TIMEOUT", "30")
            ),
            max_retries=int(os.environ.get("FEDERAL_REGISTER_MAX_RETRIES", "3")),
            backoff_initial_seconds=float(
                os.environ.get("FEDERAL_REGISTER_BACKOFF_INITIAL", "1")
            ),
            backoff_max_seconds=float(
                os.environ.get("FEDERAL_REGISTER_BACKOFF_MAX", "30")
            ),
            retry_after_max_seconds=float(
                os.environ.get("FEDERAL_REGISTER_RETRY_AFTER_MAX", "60")
            ),
            max_response_bytes=int(
                os.environ.get("FEDERAL_REGISTER_MAX_RESPONSE_BYTES", "33554432")
            ),
            user_agent=os.environ.get(
                "FEDERAL_REGISTER_USER_AGENT", "maiven-takehome-ingest/0.1"
            ),
        )

    def __post_init__(self) -> None:
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("HTTP timeouts must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if (
            self.backoff_initial_seconds < 0
            or self.backoff_max_seconds < 0
            or self.retry_after_max_seconds < 0
        ):
            raise ValueError("retry backoff values cannot be negative")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if not self.user_agent.strip():
            raise ValueError("User-Agent cannot be empty")


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_url: str
    repository_root: Path
    client: ClientSettings

    @classmethod
    def from_env(cls) -> AppSettings:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is missing; run the CLI through the root Varlock setup "
                "(see pipelines/ingest/README.md)"
            )
        return cls(
            database_url=database_url,
            repository_root=repository_root(),
            client=ClientSettings.from_env(),
        )
