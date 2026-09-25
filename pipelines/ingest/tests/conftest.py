from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture
def page_one() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "page-1.json").read_text())


@pytest.fixture
def page_two() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "page-2.json").read_text())


def document(
    document_number: str,
    *,
    title: str | None = None,
    publication_date: str = "2026-09-20",
    agencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "document_number": document_number,
        "title": title or f"Test title {document_number}",
        "type": "RULE",
        "publication_date": publication_date,
        "effective_on": None,
        "abstract": "A test abstract.",
        "agencies": agencies
        if agencies is not None
        else [{"name": "Environmental Protection Agency", "slug": "environmental-protection-agency"}],
        "html_url": f"https://example.test/documents/{document_number}",
    }
