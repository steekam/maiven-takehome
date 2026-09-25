from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


def configure_diagnostics(repository_root: Path):
    diagnostics_path = repository_root / "logs" / "ingest.jsonl"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        diagnostics_path,
        level="INFO",
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )
    return logger.bind(service="ingest")


def read_transport_failures(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    failures: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as log_file:
        for line in log_file:
            try:
                log_record = json.loads(line).get("record", {})
            except json.JSONDecodeError:
                continue
            extra = log_record.get("extra", {})
            if extra.get("run_id") != run_id or extra.get("event") != "http_transport_error":
                continue
            failures.append(
                {
                    "request_id": extra.get("request_id"),
                    "page": extra.get("page"),
                    "attempt": extra.get("attempt"),
                    "requested_url": extra.get("requested_url"),
                    "error_class": extra.get("error_class"),
                    "archive_path": None,
                    "content_sha256": None,
                    "committed": False,
                }
            )
    return failures
