"""Schemas for stage 4 (consolidated report across documents).

The model sees documents as short labels ("D1", "D2"), not UUIDs, because a
small model copies short labels far more reliably than 36-character IDs
(DECISIONS D-035). ``*ModelOutput`` classes use those labels; the pipeline maps
them back to document IDs and checks every citation before building the
API schema ``ConsolidatedReport``.
"""

from pydantic import BaseModel, Field

from app.schemas.common import Citation, DocumentWarning

# --------------------------------------------------------------------------- model output


class LabelCitation(BaseModel):
    """A citation as the model writes it: document label plus page."""

    document: str = Field(description='Document label, e.g. "D1"')
    page: int = Field(description="1-based page within that document")


class ThemeModel(BaseModel):
    theme: str
    citations: list[LabelCitation]


class AgreementModel(BaseModel):
    point: str
    citations: list[LabelCitation]


class PositionModel(BaseModel):
    position: str
    citation: LabelCitation


class ContradictionModel(BaseModel):
    topic: str
    positions: list[PositionModel]


class TimelineEventModel(BaseModel):
    time: str
    event: str
    citations: list[LabelCitation]


class DocumentGroupModel(BaseModel):
    documents: list[str] = Field(description='Document labels, e.g. ["D1", "D3"]')
    reason: str


class ConsolidatedModelOutput(BaseModel):
    """What the model produces for the consolidated report."""

    overall_summary: str
    common_themes: list[ThemeModel]
    agreements: list[AgreementModel]
    contradictions: list[ContradictionModel]
    timeline: list[TimelineEventModel]
    related_document_groups: list[DocumentGroupModel]
    information_gaps: list[str]


# --------------------------------------------------------------------------- API output


class Theme(BaseModel):
    theme: str
    citations: list[Citation]


class Agreement(BaseModel):
    point: str
    citations: list[Citation]


class Position(BaseModel):
    position: str
    citation: Citation


class Contradiction(BaseModel):
    topic: str
    positions: list[Position]


class TimelineEvent(BaseModel):
    time: str
    event: str
    citations: list[Citation]


class DocumentGroup(BaseModel):
    document_ids: list[str]
    reason: str


class IncidentNarrativeOutput(BaseModel):
    """Incident profile: the model writes only the narrative parts of the report.

    Contradictions, agreements, the timeline and same-incident groups are
    computed by code from the extracted facts (DECISIONS D-057), so the model is
    not asked for them.
    """

    overall_summary: str
    common_themes: list[ThemeModel]
    information_gaps: list[str]


class ConsolidatedReport(BaseModel):
    """One per job (CLAUDE.md section 8).

    ``warnings`` is an addition to the spec. It tells the analyst when citations
    the model invented were removed (DECISIONS D-034).
    """

    overall_summary: str
    common_themes: list[Theme]
    agreements: list[Agreement]
    contradictions: list[Contradiction]
    timeline: list[TimelineEvent]
    related_document_groups: list[DocumentGroup]
    information_gaps: list[str]
    warnings: list[DocumentWarning] = Field(default_factory=list)
    # Incident profile (addition, D-057): pairs whose date and time match but whose
    # location is missing or does not match. Never used for contradictions.
    possibly_related_groups: list[DocumentGroup] = Field(default_factory=list)
    # True when contradictions/agreements/timeline/groups were computed by rule (incident).
    rule_based: bool = False
