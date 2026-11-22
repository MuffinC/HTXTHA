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
from dataclasses import dataclass

from app.config import Settings
from app.llm.base import LLMProvider, LLMRequest, LLMTask
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline import incident_rules, triage_rules
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
    IncidentNarrativeOutput,
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

    # Incident profile: groups, contradictions, agreements and the timeline are
    # computed by rule; the model only writes the narrative parts (D-057).
    incident = all(a.profile == "incident" for a in analyses)
    rule = _incident_rule_findings(by_label) if incident else None

    wrapped, boundary = wrap_untrusted(content)
    if rule is not None:
        prompt = render_prompt(
            "consolidation_incident",
            count=len(by_label),
            labels=labels,
            boundary=boundary,
            content=wrapped,
            findings=rule.findings,
        )
    else:
        prompt = render_prompt(
            "consolidation", count=len(by_label), labels=labels, boundary=boundary, content=wrapped
        )
    request = LLMRequest(
        task=LLMTask.CONSOLIDATION,
        system=load_prompt("system"),
        prompt=prompt,
        json_schema={},
        max_output_tokens=CONSOLIDATION_OUTPUT_TOKENS,
        metadata={"documents": {label: a.page_count for label, a in by_label.items()}},
    )
    if rule is not None:
        narrative, _ = await generate_structured(
            provider, request, IncidentNarrativeOutput, retries=CONSOLIDATION_RETRIES
        )
        output = ConsolidatedModelOutput(
            overall_summary=narrative.overall_summary,
            common_themes=narrative.common_themes,
            agreements=[],
            contradictions=[],
            timeline=[],
            related_document_groups=[],
            information_gaps=narrative.information_gaps,
        )
    else:
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
    if rule is not None:
        if rule.excluded:
            # Zero contradictions must not look like agreement when a report was left out.
            report.warnings.append(
                DocumentWarning(
                    code=WarningCode.INCIDENT_EXTRACTION_FAILED,
                    message=f"{', '.join(rule.excluded)} could not be compared: their incident "
                    "facts were not extracted, so they take no part in grouping, contradictions "
                    "or the timeline.",
                )
            )
        report.contradictions = rule.contradictions
        report.agreements = rule.agreements
        report.timeline = rule.timeline
        report.related_document_groups = _with_group_priorities(
            rule.grouping.same_incident, rule.contradictions, by_label
        )
        report.possibly_related_groups = rule.grouping.possibly_related
        report.rule_based = True
        report.rule_summary = incident_rules.grouping_summary(
            rule.grouping, compared=len(by_label) - len(rule.excluded), excluded=len(rule.excluded)
        )
    return report


def _with_group_priorities(
    groups: list[DocumentGroup],
    contradictions: list[Contradiction],
    by_label: dict[str, DocumentAnalysis],
) -> list[DocumentGroup]:
    """Attach each same-incident group's priority (triage_rules.group_priority)."""
    triage = {a.document_id: a.triage for a in by_label.values() if a.triage}
    many = len(groups) > 1
    result: list[DocumentGroup] = []
    for i, group in enumerate(groups, start=1):
        members = {d: triage[d].suggested_priority for d in group.document_ids if d in triage}
        if not members:
            result.append(group)
            continue
        suffix = f" (incident {i})"
        own = [c for c in contradictions if not many or c.topic.endswith(suffix)]
        gp = triage_rules.group_priority(members, own)
        result.append(
            group.model_copy(update={"priority": gp.priority, "priority_reason": gp.reason})
        )
    return result


@dataclass
class IncidentRuleFindings:
    """Rule-based cross-ticket results, plus a plain-text version for the prompt."""

    grouping: incident_rules.Grouping
    contradictions: list[Contradiction]
    agreements: list[Agreement]
    timeline: list[TimelineEvent]
    findings: str
    #: Labels of documents whose incident extraction failed (not compared).
    excluded: list[str]


def _incident_rule_findings(by_label: dict[str, DocumentAnalysis]) -> IncidentRuleFindings:
    """Group the tickets and compare their facts by rule (app.pipeline.incident_rules).

    Documents whose incident extraction failed take no part in the rules.
    """
    tickets = [
        incident_rules.ticket_for_comparison(
            document_id=a.document_id,
            label_=label,
            category=a.incident.ticket.category,
            location=a.incident.location_stated,
            derived=a.incident.derived,
            time_as_written=a.incident.occurred_at_stated,
            facts=a.incident.facts,
        )
        for label, a in by_label.items()
        if a.incident is not None
    ]
    grouping = incident_rules.group_incidents(tickets)
    contradictions: list[Contradiction] = []
    agreements: list[Agreement] = []
    many = len(grouping.groups) > 1
    for i, group in enumerate(grouping.groups, start=1):
        found, agreed = incident_rules.compare_group(
            group, suffix=f" (incident {i})" if many else ""
        )
        contradictions += found
        agreements += agreed

    # Plain-text findings for the prompt. Only labels, field names and closed-list
    # values: no quoted document text appears outside the untrusted-content markers.
    labels_by_id = {t.document_id: t.label for t in tickets}
    lines: list[str] = []
    grouped: set[str] = set()
    for group in grouping.groups:
        lines.append(f"- Same incident: {', '.join(t.label for t in group)}.")
        grouped |= {t.document_id for t in group}
    for pair in grouping.possibly_related:
        pair_labels = ", ".join(labels_by_id[d] for d in pair.document_ids)
        lines.append(f"- Possibly related, not confirmed: {pair_labels}.")
    separate = [t.label for t in tickets if t.document_id not in grouped]
    if separate:
        lines.append(
            f"- Separate incidents (no match by date, time and place): {', '.join(separate)}."
        )
    for c in contradictions:
        values = "; ".join(p.position.split(" (“")[0] for p in c.positions)
        lines.append(f"- Contradiction on {c.topic}: {values}.")
    for a in agreements:
        lines.append(f"- Agreement: {a.point.split(' (every')[0]}.")
    if not lines:
        lines.append("- No incident facts could be compared.")
    return IncidentRuleFindings(
        grouping=grouping,
        contradictions=contradictions,
        agreements=agreements,
        timeline=incident_rules.build_timeline(tickets),
        findings="\n".join(lines),
        excluded=[label for label, a in by_label.items() if a.incident is None],
    )


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
    if a.incident:
        lines.append(f"Incident location (as written): {a.incident.location_stated}")
        lines.append(f"Incident time (as written): {a.incident.occurred_at_stated}")
    if a.visual_elements:
        lines.append("Visual elements (AI descriptions of images):")
        lines += [
            f"- (p.{v.page}) {v.type}: {v.description}" for v in a.visual_elements[:MAX_VISUALS]
        ]
    return "\n".join(lines)
