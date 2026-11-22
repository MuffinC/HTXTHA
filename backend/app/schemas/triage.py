"""Schemas for triage (the optional AI feature, incident profile only; DECISIONS D-062).

Hybrid design: code computes a minimum priority (the "rule floor") from the
extracted facts using the CLAUDE.md section-8 rubric; the model may only RAISE
it, with a verbatim quote that code checks against the page text. The final
suggestion is the more severe of the two. ``requires_human_review`` is always
true: the analyst confirms or overrides every suggestion.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Citation

Priority = Literal["P1", "P2", "P3", "P4"]
#: Most severe first.
PRIORITY_ORDER: tuple[Priority, ...] = ("P1", "P2", "P3", "P4")


class TriageFactor(BaseModel):
    """One reason behind a priority, with the page that supports it."""

    factor: str
    citation: Citation
    # Addition to the spec: where the factor came from.
    source: Literal["rule", "model"]


class AnalystOverride(BaseModel):
    """The analyst's decision on a suggestion (latest one is shown)."""

    # Addition to the spec: "confirm" keeps the suggestion; "override" changes it.
    action: Literal["confirm", "override"]
    priority: Priority
    reason: str
    at: datetime


class Triage(BaseModel):
    """Suggested priority for one incident report (CLAUDE.md section 8, plus additions)."""

    suggested_priority: Priority
    rationale: str
    triggering_factors: list[TriageFactor]
    confidence: Literal["low", "medium", "high"]
    requires_human_review: Literal[True] = True
    analyst_override: AnalystOverride | None = None
    # Additions: the two inputs to the suggestion, so the UI can show why.
    rule_priority: Priority
    model_priority: Priority | None = Field(
        default=None, description="The model's proposal if it was a grounded raise"
    )


# --------------------------------------------------------------------------- model output


class TriageEvidence(BaseModel):
    quote: str = Field(max_length=200, description="Verbatim words from the page")
    page: int


class TriageModelOutput(BaseModel):
    """What the model may propose: a priority and, to raise it, quoted evidence."""

    proposed_priority: Priority
    reason: str = Field(max_length=300)
    evidence: list[TriageEvidence] = Field(max_length=4)
    confidence: Literal["low", "medium", "high"]


# --------------------------------------------------------------------------- API


class TriageReviewRequest(BaseModel):
    """Body of ``PUT /api/jobs/{job_id}/documents/{document_id}/triage``."""

    action: Literal["confirm", "override"]
    priority: Priority | None = None
    reason: str | None = Field(default=None, max_length=500)


class FeedbackRequest(BaseModel):
    """Body of ``POST /api/jobs/{job_id}/feedback``."""

    target: Literal["document", "consolidated", "section"]
    target_id: str = Field(min_length=1, max_length=120)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackCreated(BaseModel):
    id: int


class FeedbackStats(BaseModel):
    """Body of ``GET /api/feedback/stats``."""

    ratings: dict[str, dict[str, int]] = Field(
        description='Counts per target, e.g. {"section:summary": {"up": 3, "down": 1}}'
    )
    total_up: int
    total_down: int
    triage_reviewed: int = Field(description="Reports an analyst confirmed or overrode")
    triage_kept: int = Field(description="Of those, how many kept the suggested priority")
    triage_agreement_rate: float | None = Field(
        description="triage_kept / triage_reviewed, or null before any review"
    )
