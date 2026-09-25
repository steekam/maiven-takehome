from __future__ import annotations

import re
from pathlib import Path

from maiven_ingest.fields import DOCUMENT_FIELDS, JSONB_FIELDS


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "packages" / "db" / "src" / "schema.ts"
INTERNAL_DOCUMENT_COLUMNS = {"updated_at"}


def _documents_columns() -> dict[str, str]:
    schema = SCHEMA_PATH.read_text()
    table = re.search(
        r'export const documents = pgTable\(\s*"documents",\s*\{(?P<columns>.*?)\n\s*\},\s*\(table\)',
        schema,
        re.DOTALL,
    )
    assert table is not None, f"Could not find the Drizzle documents table in {SCHEMA_PATH}"

    matches = list(
        re.finditer(
            r'^\s*\w+\s*:\s*(?P<kind>\w+)\("(?P<column>[a-z0-9_]+)"',
            table.group("columns"),
            re.MULTILINE,
        )
    )
    columns = {
        match.group("column"): match.group("kind")
        for match in matches
    }
    assert columns, f"Could not parse columns from the Drizzle documents table in {SCHEMA_PATH}"
    assert len(columns) == len(matches), "Drizzle documents table contains duplicate SQL columns"
    return columns


def _difference_message(label: str, expected: set[str], actual: set[str]) -> str:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    return f"{label} drift; missing from Drizzle={missing}, missing from Python={extra}"


def test_document_fields_match_drizzle_documents_columns():
    columns = _documents_columns()
    drizzle_fields = set(columns) - INTERNAL_DOCUMENT_COLUMNS
    python_fields = set(DOCUMENT_FIELDS)

    assert len(DOCUMENT_FIELDS) == len(python_fields), "DOCUMENT_FIELDS contains duplicates"
    assert python_fields == drizzle_fields, _difference_message(
        "DOCUMENT_FIELDS", python_fields, drizzle_fields
    )


def test_jsonb_fields_match_drizzle_documents_jsonb_columns():
    columns = _documents_columns()
    drizzle_jsonb_fields = {
        column for column, kind in columns.items() if kind == "jsonb"
    }
    python_jsonb_fields = set(JSONB_FIELDS)

    assert len(JSONB_FIELDS) == len(python_jsonb_fields), "JSONB_FIELDS contains duplicates"
    assert python_jsonb_fields == drizzle_jsonb_fields, _difference_message(
        "JSONB_FIELDS", python_jsonb_fields, drizzle_jsonb_fields
    )
