"""Stage 4: consolidated report across the documents of a job.

Input is only the per-document structured outputs (summary, topics, entities,
notable points, visual descriptions), never raw text, as the spec requires,
so even ten documents fit the context.

Documents are shown to the model as short labels (D1, D2...) instead of UUIDs:
a small model copies "D2" reliably but often mangles a 36-character ID
(DECISIONS D-035). Labels are mapped back to document IDs afterwards, and every
citation is checked: an unknown label or a page outside the cited document is
removed, and the removal is counted in the logs and reported as a warning.
"""

import logging
import re

from app.config import Settings
from app.llm.base import LLMProvider, LLMRequest, LLMTask
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline.budget import content_budget_tokens, estimate_tokens, truncate_to_tokens
from app.pipeline.citations import is_valid_page, removed_citations_warning
from app.schemas.analysis import DocumentAnalysis
from app.schemas.common import Citation, DocumentWarning, WarningCode
from app.schemas.consolidated import (
    Agreement,
    ConsolidatedModelOutput,
    ConsolidatedReport,
    Contradiction,
    DocumentGroup,
    LabelCitation,
    Position,
    Theme,
    TimelineEvent,
)
from app.security.boundary import wrap_untrusted
from app.security.pii import mask_pii_in

logger = logging.getLogger(__name__)

CONSOLIDATION_OUTPUT_TOKENS = 4096
CONSOLIDATION_RETRIES = 1
# Per-document caps on what is sent, so ten documents stay well inside the budget.
MAX_POINTS, MAX_ENTITIES, MAX_VISUALS = 12, 15, 6

# Tolerates "D2", "d2", "D 2" and "Document D2"; anything else is an unknown label.
_LABEL = re.compile(r"^\s*(?:document\s+)?d\s*(\d+)\s*$", re.IGNORECASE)


async def consolidate(
    analyses: list[DocumentAnalysis], provider: LLMProvider, settings: Settings
) -> ConsolidatedReport:
    """Build the consolidated report for two or more analysed documents.

    Raises:
        LLMError: The model failed or its output was invalid after one retry.
            The worker records this as ``consolidated_error``; documents are unaffected.
    """
    by_label = {f"D{i}": a for i, a in enumerate(analyses, start=1)}
    labels = ", ".join(by_label)
    warnings: list[DocumentWarning] = []

    content = "\n\n".join(_describe(label, a) for label, a in by_label.items())
    budget = content_budget_tokens(settings.ollama_num_ctx, CONSOLIDATION_OUTPUT_TOKENS)
    if estimate_tokens(content) > budget:
        content = truncate_to_tokens(content, budget)
        warnings.append(
            DocumentWarning(
                code=WarningCode.CONTENT_TRUNCATED,
                message=(
                    "The document analyses were too long to compare in full; the last "
                    "documents may be under-represented in this report."
                ),
            )
        )

    wrapped, boundary = wrap_untrusted(content)
    request = LLMRequest(
        task=LLMTask.CONSOLIDATION,
        system=load_prompt("system"),
        prompt=render_prompt(
            "consolidation", count=len(by_label), labels=labels, boundary=boundary, content=wrapped
        ),
        json_schema={},
        max_output_tokens=CONSOLIDATION_OUTPUT_TOKENS,
        metadata={"documents": {label: a.page_count for label, a in by_label.items()}},
    )
    output, _ = await generate_structured(
        provider, request, ConsolidatedModelOutput, retries=CONSOLIDATION_RETRIES
    )

    # Mask while documents are still short labels (D1, D2), BEFORE they become
    # UUIDs: a UUID such as "...-cb96609844e7" contains a phone-like digit run,
    # and masking it would break the citation (found in M5 screenshots; D-053).
    if settings.mask_pii:
        output = ConsolidatedModelOutput.model_validate(mask_pii_in(output.model_dump()))

    report, removed = resolve_citations(output, by_label)
    warning = removed_citations_warning(removed, "the consolidated report")
    if warning:
        warnings.append(warning)
    report.warnings = warnings
    return report


def resolve_citations(
    output: ConsolidatedModelOutput, by_label: dict[str, DocumentAnalysis]
) -> tuple[ConsolidatedReport, int]:
    """Map labels to document IDs and drop citations that point nowhere.

    Items left with no valid citation are dropped too (they cannot be verified),
    as are contradictions with fewer than two positions and document groups
    with fewer than two documents.

    Returns:
        The API report (without warnings) and the number of citations removed.
    """
    removed = 0

    def resolve(c: LabelCitation) -> Citation | None:
        nonlocal removed
        doc = _lookup(c.document, by_label)
        if doc is None or not is_valid_page(c.page, doc.page_count):
            removed += 1
            return None
        return Citation(document_id=doc.document_id, page=c.page)

    def resolve_all(cs: list[LabelCitation]) -> list[Citation]:
        return [r for c in cs if (r := resolve(c)) is not None]

    themes = [
        Theme(theme=t.theme, citations=cs)
        for t in output.common_themes
        if (cs := resolve_all(t.citations))
    ]
    agreements = [
        Agreement(point=a.point, citations=cs)
        for a in output.agreements
        if (cs := resolve_all(a.citations))
    ]
    timeline = [
        TimelineEvent(time=e.time, event=e.event, citations=cs)
        for e in output.timeline
        if (cs := resolve_all(e.citations))
    ]
    contradictions = []
    for c in output.contradictions:
        positions = [
            Position(position=p.position, citation=r)
            for p in c.positions
            if (r := resolve(p.citation)) is not None
        ]
        if len(positions) >= 2:
            contradictions.append(Contradiction(topic=c.topic, positions=positions))
    groups = []
    for g in output.related_document_groups:
        ids = []
        for label in g.documents:
            doc = _lookup(label, by_label)
            if doc is None:
                removed += 1
            elif doc.document_id not in ids:
                ids.append(doc.document_id)
        if len(ids) >= 2:
            groups.append(DocumentGroup(document_ids=ids, reason=g.reason))

    # Items left blank once pipeline markers were stripped carry no information.
    report = ConsolidatedReport(
        overall_summary=output.overall_summary,
        common_themes=[t for t in themes if t.theme.strip()],
        agreements=[a for a in agreements if a.point.strip()],
        contradictions=[c for c in contradictions if c.topic.strip()],
        timeline=[e for e in timeline if e.event.strip()],
        related_document_groups=groups,
        information_gaps=output.information_gaps,
    )
    return report, removed


def _lookup(label: str, by_label: dict[str, DocumentAnalysis]) -> DocumentAnalysis | None:
    match = _LABEL.match(label)
    return by_label.get(f"D{match.group(1)}") if match else None


def _describe(label: str, a: DocumentAnalysis) -> str:
    """One document's structured analysis as plain text for the prompt."""
    lines = [
        f"=== Document {label} ({a.page_count} pages) ===",
        f"Type: {a.document_type_guess}",
        f"Summary: {a.summary}",
        f"Topics: {'; '.join(a.main_topics)}",
        "Notable points:",
        *[f"- (p.{p.page}) {p.point}" for p in a.notable_points[:MAX_POINTS]],
        "Key entities:",
        *[
            f"- {e.name} [{e.type}] (p.{', p.'.join(str(n) for n in e.pages)})"
            for e in a.key_entities[:MAX_ENTITIES]
        ],
    ]
    if a.visual_elements:
        lines.append("Visual elements (AI descriptions of images):")
        lines += [
            f"- (p.{v.page}) {v.type}: {v.description}" for v in a.visual_elements[:MAX_VISUALS]
        ]
    return "\n".join(lines)
