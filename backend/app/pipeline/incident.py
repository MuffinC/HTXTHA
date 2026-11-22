"""Incident profile, stage 3b: extract the reporter's facts, then apply the code rules.

One extra model call per document (DECISIONS D-057). The model fills
``IncidentExtractionOutput`` (ticket header, normalised facts with quotes and
pages, parties by role, other claims). Everything else, including derived
dates and times, narrative-against-photo checks, claim corroboration and
missing information, is computed by ``app.pipeline.incident_rules``.
"""

import logging
import re

from app.config import Settings
from app.llm.base import LLMProvider, LLMRequest, LLMTask
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline import incident_rules as rules
from app.pipeline.citations import is_valid_page, removed_citations_warning
from app.schemas.common import DocumentWarning
from app.schemas.incident import IncidentExtension, IncidentExtractionOutput, TicketInfo
from app.schemas.visual import VisualElement
from app.security.boundary import wrap_untrusted
from app.security.pii import mask_pii_in

logger = logging.getLogger(__name__)

EXTRACTION_OUTPUT_TOKENS = 2048
EXTRACTION_RETRIES = 1


async def extract_incident(
    *,
    content: str,
    content_description: str,
    page_count: int,
    visual_elements: list[VisualElement],
    provider: LLMProvider,
    settings: Settings,
    mock_meta: dict[str, object],
) -> tuple[IncidentExtension, list[DocumentWarning]]:
    """Run the extraction call and build the incident extension.

    Args:
        content: The same page-headed text (or notes) the core analysis used.
        content_description: How ``content`` is laid out (full text or notes).
        page_count: For citation checks.
        visual_elements: Stage-2 output; photo scenes are compared with the narrative.
        provider: LLM provider.
        settings: PII masking.
        mock_meta: Request metadata for the mock provider (page texts).

    Raises:
        LLMError: The call failed or stayed invalid after one retry. The caller
            keeps the core analysis and adds an ``INCIDENT_EXTRACTION_FAILED`` warning.
    """
    wrapped, boundary = wrap_untrusted(content)
    request = LLMRequest(
        task=LLMTask.INCIDENT_EXTRACTION,
        system=load_prompt("system"),
        prompt=render_prompt(
            "incident_extraction",
            page_count=page_count,
            content_description=content_description,
            boundary=boundary,
            content=wrapped,
        ),
        json_schema={},
        max_output_tokens=EXTRACTION_OUTPUT_TOKENS,
        metadata=mock_meta,
    )
    extraction, _ = await generate_structured(
        provider, request, IncidentExtractionOutput, retries=EXTRACTION_RETRIES
    )
    warnings: list[DocumentWarning] = []
    extraction = _normalise_header(extraction)
    extraction, removed = _clean_pages(extraction, page_count)
    warning = removed_citations_warning(removed, "the incident facts")
    if warning:
        warnings.append(warning)
    # A stated value must be supported by its own quote (D-058).
    grounded, downgraded = rules.ground_facts(extraction.facts)
    if downgraded:
        logger.info(
            "Incident facts downgraded (ungrounded) or corrected (weapon negation)",
            extra={"stage": "analysing", "event": "facts_ungrounded", "count": len(downgraded)},
        )
        extraction = extraction.model_copy(update={"facts": grounded})
    # After grounding, so only quotes that still back a stated fact count (D-080).
    extraction, repeated = rules.drop_repeated_claims(extraction)
    if repeated:
        logger.info(
            "Other claims dropped (repeat a fact quote)",
            extra={"stage": "analysing", "event": "claims_repeated", "count": repeated},
        )
    if settings.mask_pii:
        extraction = IncidentExtractionOutput.model_validate(mask_pii_in(extraction.model_dump()))

    derived = rules.derive_facts(extraction)
    photos = [rules.PhotoScene(page=v.page, scene=v.scene) for v in visual_elements if v.scene]
    checks, by_field = rules.check_narrative_against_photos(extraction.facts, derived, photos)
    occurred = " ".join(t for t in (extraction.occurred_date, extraction.occurred_time) if t)

    incident = IncidentExtension(
        ticket=TicketInfo(
            reference_no=extraction.reference_no,
            submitted_at=extraction.submitted_at,
            category=extraction.category,
            category_confidence=extraction.category_confidence,
        ),
        occurred_at_stated=occurred or None,
        location_stated=extraction.location,
        narrative_summary=extraction.narrative_summary,
        parties=extraction.parties,
        claims=rules.build_claims(extraction, by_field, has_photo=bool(photos)),
        consistency_checks=checks,
        missing_information=rules.missing_information(extraction, derived, has_photo=bool(photos)),
        facts=extraction.facts,
        derived=derived,
    )
    logger.info(
        "Incident facts extracted",
        extra={"stage": "analysing", "event": "incident_extracted", "count": len(checks)},
    )
    return incident, warnings


# The model sometimes writes a placeholder such as "not_mentioned" into a free-text
# header field instead of null (seen in live runs); treat those as missing.
_PLACEHOLDER = re.compile(
    r"^\W*(?:not[ _]?(?:mentioned|stated|given)|n/?a|none|null|unknown|-)\W*$", re.I
)
_HEADER_FIELDS = ("reference_no", "submitted_at", "occurred_date", "occurred_time", "location")


def _normalise_header(extraction: IncidentExtractionOutput) -> IncidentExtractionOutput:
    """Replace placeholder strings in the ticket header fields with None."""
    updates = {
        name: None
        for name in _HEADER_FIELDS
        if (value := getattr(extraction, name)) is not None and _PLACEHOLDER.match(value)
    }
    return extraction.model_copy(update=updates) if updates else extraction


def _clean_pages(
    extraction: IncidentExtractionOutput, page_count: int
) -> tuple[IncidentExtractionOutput, int]:
    """Null fact pages that do not exist and drop other claims citing them (D-034)."""
    removed = 0
    facts = extraction.facts.model_copy()
    for name in rules.COMPARED_FIELDS:
        fact = getattr(facts, name)
        if fact.page is not None and not is_valid_page(fact.page, page_count):
            setattr(facts, name, fact.model_copy(update={"page": None}))
            removed += 1
    claims = [c for c in extraction.other_claims if is_valid_page(c.page, page_count)]
    removed += len(extraction.other_claims) - len(claims)
    return extraction.model_copy(update={"facts": facts, "other_claims": claims}), removed
