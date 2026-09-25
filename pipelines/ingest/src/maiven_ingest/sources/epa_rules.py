from maiven_ingest.fields import DOCUMENT_FIELDS
from maiven_ingest.models import DocumentSearch


EPA_AGENCY = "environmental-protection-agency"


def epa_rules_search(
    *,
    per_page: int = 100,
    publication_date_gte: str | None = None,
    publication_date_lte: str | None = None,
) -> DocumentSearch:
    return DocumentSearch(
        agencies=(EPA_AGENCY,),
        document_types=("RULE",),
        per_page=per_page,
        order="newest",
        fields=DOCUMENT_FIELDS,
        publication_date_gte=publication_date_gte,
        publication_date_lte=publication_date_lte,
    )
