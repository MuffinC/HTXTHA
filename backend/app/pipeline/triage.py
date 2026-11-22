"""Triage for one incident report: rule floor plus a grounded model raise (D-062).

Runs right after incident extraction (stage 3), while the page text is still
available for checking the model's quotes; uploads are deleted after
processing. Each report's priority depends only on its own facts and text, so
nothing here needs the other reports. The group priority is computed later,
in consolidation (``triage_rules.group_priority``).

If the model call fails, the suggestion falls back to the rule floor: triage
never fails a document.
"""

import logging

from app.config import Settings
from app.llm.base import LLMError, LLMProvider, LLMRequest, LLMTask
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline import triage_rules as rules
from app.schemas.incident import IncidentExtension
from app.schemas.triage import Triage, TriageModelOutput
from app.security.boundary import wrap_untrusted
from app.security.pii import mask_pii

logger = logging.getLogger(__name__)

TRIAGE_OUTPUT_TOKENS = 1024


async def triage_document(
    *,
    document_id: str,
    incident: IncidentExtension,
    content: str,
    content_description: str,
    page_count: int,
    page_texts: dict[int, str],
    provider: LLMProvider,
    settings: Settings,
    mock_meta: dict[str, object],
) -> Triage:
    """Suggest a priority for one incident report.

    Args:
        page_texts: The document's own extracted text per page (not AI visual
            descriptions), against which the model's quotes are checked.
    """
    floor = rules.rule_floor(incident, document_id)
    floor_text = f"{floor.priority}. Factors: " + "; ".join(f.factor for f in floor.factors)
    wrapped, boundary = wrap_untrusted(content)
    request = LLMRequest(
        task=LLMTask.TRIAGE,
        system=load_prompt("system"),
        prompt=render_prompt(
            "triage",
            page_count=page_count,
            content_description=content_description,
            boundary=boundary,
            content=wrapped,
            floor=floor_text,
        ),
        json_schema={},
        max_output_tokens=TRIAGE_OUTPUT_TOKENS,
        metadata={**mock_meta, "rule_floor": floor.priority},
    )
    try:
        proposal, _ = await generate_structured(provider, request, TriageModelOutput, retries=1)
    except LLMError as exc:
        logger.warning("Triage model check failed", extra={"stage": "analysing", "code": exc.code})
        return Triage(
            suggested_priority=floor.priority,
            rationale=floor.rationale + " (The model check was unavailable; rule floor only.)",
            triggering_factors=floor.factors,
            confidence="low",
            rule_priority=floor.priority,
        )

    escalation = rules.ground_escalation(proposal, floor.priority, page_texts, document_id)
    if rules.is_raise(proposal.proposed_priority, floor.priority) and not escalation.accepted:
        logger.warning(
            "Ungrounded triage raise ignored",
            extra={
                "stage": "analysing",
                "event": "triage_raise_ignored",
                "code": proposal.proposed_priority,
            },
        )
    final, rationale = rules.combine(floor, escalation, proposal.confidence)
    triage = Triage(
        suggested_priority=final,
        rationale=rationale,
        triggering_factors=[*floor.factors, *escalation.factors],
        confidence=proposal.confidence if escalation.accepted else _rule_confidence(floor),
        rule_priority=floor.priority,
        model_priority=escalation.priority,
    )
    return _mask_text(triage) if settings.mask_pii else triage


def _mask_text(triage: Triage) -> Triage:
    """Mask PII in the free text only (model quotes can contain a phone number).

    Citations carry document IDs and are never masked: masking the whole dump once
    turned a UUID like "...-8123-4567-..." into "[PHONE REDACTED]" (DECISIONS D-070).
    """
    return triage.model_copy(
        update={
            "rationale": mask_pii(triage.rationale),
            "triggering_factors": [
                f.model_copy(update={"factor": mask_pii(f.factor)})
                for f in triage.triggering_factors
            ],
        }
    )


def _rule_confidence(floor: rules.RuleResult) -> str:
    """High when a stated fact set the floor; low when nothing in the rubric applied."""
    return "low" if floor.priority == "P4" else "high"
