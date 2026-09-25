from __future__ import annotations

import re
from datetime import date
from typing import Any

from maiven_ingest.fields import DOCUMENT_FIELDS, REQUIRED_FIELDS
from maiven_ingest.models import MalformedPayloadError


TEXT_FIELDS = frozenset(
    {
        "abstract",
        "action",
        "body_html_url",
        "citation",
        "comment_url",
        "dates",
        "disposition_notes",
        "docket_id",
        "document_number",
        "excerpts",
        "executive_order_notes",
        "executive_order_number",
        "explanation",
        "full_text_xml_url",
        "html_url",
        "json_url",
        "mods_url",
        "presidential_document_number",
        "proclamation_number",
        "public_inspection_pdf_url",
        "raw_text_url",
        "regulations_dot_gov_url",
        "subtype",
        "title",
        "toc_doc",
        "toc_subject",
        "type",
    }
)
DATE_FIELDS = frozenset(
    {"comments_close_on", "effective_on", "publication_date", "signing_date"}
)
INTEGER_FIELDS = frozenset({"end_page", "page_length", "start_page", "volume"})
BOOLEAN_FIELDS = frozenset({"not_received_for_publication", "significant"})
WHITESPACE = re.compile(r"\s+")
TRANSFORM_VERSION = "2"


def clean_text(value: str) -> str:
    return WHITESPACE.sub(" ", value).strip()


def normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if field not in document]
    if missing:
        raise MalformedPayloadError(
            "Federal Register document is missing required fields: "
            + ", ".join(sorted(missing))
        )

    row: dict[str, Any] = {}
    for field in DOCUMENT_FIELDS:
        value = document.get(field, [] if field == "agencies" else None)
        if field in REQUIRED_FIELDS and (value is None or value == ""):
            raise MalformedPayloadError(f"Federal Register document has empty {field}")
        if value is not None:
            if field in TEXT_FIELDS:
                if not isinstance(value, str):
                    raise MalformedPayloadError(f"Federal Register {field} must be text or null")
                if field in {"title", "abstract"}:
                    value = clean_text(value)
            elif field in DATE_FIELDS:
                value = _date_value(field, value)
            elif field in INTEGER_FIELDS:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise MalformedPayloadError(
                        f"Federal Register {field} must be an integer or null"
                    )
            elif field in BOOLEAN_FIELDS and not isinstance(value, bool):
                raise MalformedPayloadError(f"Federal Register {field} must be boolean or null")
        row[field] = value

    agencies = row["agencies"]
    if agencies is None:
        raise MalformedPayloadError("Federal Register agencies must be an array of objects")
    if not isinstance(agencies, list) or any(not isinstance(agency, dict) for agency in agencies):
        raise MalformedPayloadError("Federal Register agencies must be an array of objects")
    if not row["document_number"].strip():
        raise MalformedPayloadError("Federal Register document_number cannot be blank")
    if not row["title"].strip() or not row["type"].strip() or not row["html_url"].strip():
        raise MalformedPayloadError("Federal Register required text fields cannot be blank")
    return row


def _date_value(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise MalformedPayloadError(f"Federal Register {field} must be an ISO date or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise MalformedPayloadError(f"Federal Register {field} must be an ISO date or null") from error
    if parsed.isoformat() != value:
        raise MalformedPayloadError(f"Federal Register {field} must use YYYY-MM-DD")
    return value
