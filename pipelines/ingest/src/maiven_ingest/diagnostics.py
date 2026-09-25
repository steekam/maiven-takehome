from __future__ import annotations

from pathlib import Path

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
