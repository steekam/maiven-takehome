"""Federal Register field contract and normalized document shape."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from maiven_ingest.models import MalformedPayloadError

WHITESPACE = re.compile(r"\s+")
TRANSFORM_VERSION = "2"


def clean_text(value: str) -> str:
    return WHITESPACE.sub(" ", value).strip()


class FederalRegisterDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    abstract: str | None = None
    action: str | None = None
    agencies: Any = Field(default_factory=list)
    agency_names: Any = None
    amendatory_instructions: Any = None
    body_html_url: str | None = None
    cfr_references: Any = None
    cfr_topics: Any = None
    citation: str | None = None
    comment_url: str | None = None
    comments_close_on: str | None = None
    correction_of: Any = None
    corrections: Any = None
    dates: str | None = None
    disposition_notes: str | None = None
    docket_id: str | None = None
    docket_ids: Any = None
    dockets: Any = None
    document_number: str
    effective_on: str | None = None
    end_page: int | None = None
    excerpts: str | None = None
    executive_order_notes: str | None = None
    executive_order_number: str | None = None
    explanation: str | None = None
    full_text_xml_url: str | None = None
    html_url: str
    images: Any = None
    images_metadata: Any = None
    json_url: str | None = None
    mods_url: str | None = None
    not_received_for_publication: bool | None = None
    page_length: int | None = None
    page_views: Any = None
    pdf_url: str | None = None
    president: Any = None
    presidential_document_number: str | None = None
    proclamation_number: str | None = None
    public_inspection_pdf_url: str | None = None
    publication_date: str
    raw_text_url: str | None = None
    regulation_id_number_info: Any = None
    regulation_id_numbers: Any = None
    regulations_dot_gov_info: Any = None
    regulations_dot_gov_url: str | None = None
    related_documents: Any = None
    significant: bool | None = None
    signing_date: str | None = None
    start_page: int | None = None
    subtype: str | None = None
    title: str
    toc_doc: str | None = None
    toc_subject: str | None = None
    topics: Any = None
    type: str
    volume: int | None = None

    @field_validator(
        "document_number",
        "title",
        "type",
        "publication_date",
        "html_url",
        mode="before",
    )
    @classmethod
    def validate_required_values(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None or value == "":
            raise ValueError(f"Federal Register document has empty {info.field_name}")
        return value

    @field_validator("agencies")
    @classmethod
    def validate_agencies(cls, value: Any) -> Any:
        if not isinstance(value, list) or any(
            not isinstance(agency, dict) for agency in value
        ):
            raise ValueError("Federal Register agencies must be an array of objects")
        return value

    @field_validator("title", "abstract", mode="before")
    @classmethod
    def clean_display_text(cls, value: Any) -> Any:
        return clean_text(value) if isinstance(value, str) else value

    @field_validator(
        "comments_close_on", "effective_on", "publication_date", "signing_date"
    )
    @classmethod
    def validate_iso_date(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(
                f"Federal Register {info.field_name} must be an ISO date or null"
            ) from error
        if parsed.isoformat() != value:
            raise ValueError(
                f"Federal Register {info.field_name} must use YYYY-MM-DD"
            )
        return value


DOCUMENT_FIELDS = tuple(FederalRegisterDocument.model_fields)
REQUIRED_FIELDS = frozenset(
    field
    for field, definition in FederalRegisterDocument.model_fields.items()
    if definition.is_required()
)
JSONB_FIELDS = frozenset(
    {
        "agencies",
        "agency_names",
        "amendatory_instructions",
        "cfr_references",
        "cfr_topics",
        "correction_of",
        "corrections",
        "docket_ids",
        "dockets",
        "images",
        "images_metadata",
        "page_views",
        "president",
        "regulation_id_number_info",
        "regulation_id_numbers",
        "regulations_dot_gov_info",
        "related_documents",
        "topics",
    }
)


def normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_FIELDS - document.keys()
    if missing:
        raise MalformedPayloadError(
            "Federal Register document is missing required fields: "
            + ", ".join(sorted(missing))
        )

    try:
        normalized = FederalRegisterDocument.model_validate(document)
    except ValidationError as error:
        raise _malformed_payload(error) from error

    row = normalized.model_dump()
    if not row["document_number"].strip():
        raise MalformedPayloadError("Federal Register document_number cannot be blank")
    if any(not row[field].strip() for field in ("title", "type", "html_url")):
        raise MalformedPayloadError(
            "Federal Register required text fields cannot be blank"
        )
    return row


def _malformed_payload(error: ValidationError) -> MalformedPayloadError:
    validation_error = error.errors()[0]
    message = str(validation_error.get("ctx", {}).get("error", ""))
    if message.startswith("Federal Register document has empty "):
        return MalformedPayloadError(message)
    field = str(validation_error["loc"][0])
    if field == "agencies":
        return MalformedPayloadError(
            "Federal Register agencies must be an array of objects"
        )
    if field in {
        "comments_close_on",
        "effective_on",
        "publication_date",
        "signing_date",
    }:
        if "must use YYYY-MM-DD" in message:
            return MalformedPayloadError(message)
        return MalformedPayloadError(
            f"Federal Register {field} must be an ISO date or null"
        )
    if field in {"end_page", "page_length", "start_page", "volume"}:
        return MalformedPayloadError(
            f"Federal Register {field} must be an integer or null"
        )
    if field in {"not_received_for_publication", "significant"}:
        return MalformedPayloadError(
            f"Federal Register {field} must be boolean or null"
        )
    return MalformedPayloadError(f"Federal Register {field} must be text or null")
