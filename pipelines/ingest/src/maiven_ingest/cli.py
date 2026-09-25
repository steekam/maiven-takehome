from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from maiven_ingest.config import AppSettings
from maiven_ingest.diagnostics import configure_diagnostics
from maiven_ingest.federal_register.client import FederalRegisterClient
from maiven_ingest.models import IngestError
from maiven_ingest.store import IngestStore
from maiven_ingest.workflow import IngestWorkflow, epa_rules_search


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def iso_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Federal Register EPA Rules")
    parser.add_argument(
        "--max-unique-documents",
        type=positive_integer,
        default=100,
        help="unique document_number target for this run (default: 100)",
    )
    parser.add_argument(
        "--per-page",
        type=positive_integer,
        default=100,
        help="upstream Federal Register page size, independent of the run target (default: 100)",
    )
    parser.add_argument("--publication-date-gte", type=iso_date)
    parser.add_argument("--publication-date-lte", type=iso_date)
    parser.add_argument(
        "--new-run",
        action="store_true",
        help="start a separate run instead of resuming the latest incomplete run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.per_page > 1000:
        parser.error("--per-page cannot exceed the Federal Register limit of 1000")
    if (
        args.publication_date_gte
        and args.publication_date_lte
        and args.publication_date_gte > args.publication_date_lte
    ):
        parser.error("--publication-date-gte cannot be after --publication-date-lte")

    try:
        settings = AppSettings.from_env()
        event_logger = configure_diagnostics(settings.repository_root)
        search = epa_rules_search(
            per_page=args.per_page,
            publication_date_gte=args.publication_date_gte,
            publication_date_lte=args.publication_date_lte,
        )
        with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
            store = IngestStore(connection)
            with FederalRegisterClient(settings.client) as client:
                workflow = IngestWorkflow(
                    store=store,
                    client=client,
                    search=search,
                    unique_target=args.max_unique_documents,
                    repository_root=settings.repository_root,
                    logger=event_logger,
                    new_run=args.new_run,
                )
                result = workflow.run()
        print(json.dumps(result["summary"], sort_keys=True, default=_json_default))
        if result["error"]:
            print(f"ingest failed: {result['error']}", file=sys.stderr)
            return 1
        if result["summary"]["status"] == "partial":
            print(
                "ingest incomplete: Federal Register source result limit reached "
                f"before target ({result['summary']['unique_documents_seen']}/"
                f"{result['summary']['unique_target']})",
                file=sys.stderr,
            )
            return 2
        return 0
    except Exception as error:
        try:
            event_logger.bind(
                event="run_setup_failed",
                failure_class=getattr(error, "failure_class", type(error).__name__),
            ).error("run_setup_failed")
        except UnboundLocalError:
            pass
        if isinstance(error, IngestError):
            safe_error = str(error)
        elif type(error).__module__.startswith("psycopg"):
            safe_error = f"database connection failed ({type(error).__name__})"
        else:
            safe_error = str(error)
        print(f"ingest failed: {safe_error}", file=sys.stderr)
        return 1


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"cannot encode {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
