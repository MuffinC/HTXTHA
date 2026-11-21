"""Schemas for stage 3 (document analysis).

As in stage 2, there are two layers:

* ``*ModelOutput`` classes are what the model fills (their JSON schema is sent
  as Ollama's ``format``). They contain only what the model can know.
* ``DocumentAnalysis`` is the API schema from CLAUDE.md section 8. The pipeline
  adds the document ID, filename, page count, profile, visual elements and
  warnings itself, after checking every page number the model cited.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import DocumentWarning, Profile
from app.schemas.incident import IncidentExtension
from app.schemas.visual import VisualElement

EntityType = Literal[
    "person_role", "organisation", "location", "date_time", "vehicle", "object", "other"
]


class Entity(BaseModel):
    """A key entity and the pages it appears on."""

    name: str
    type: EntityType
    pages: list[int] = Field(description="1-based pages where the entity appears")


class NotablePoint(BaseModel):
    """One important point, with the page that supports it."""

    point: str
    page: int = Field(description="1-based page that supports the point")


# --------------------------------------------------------------------------- model output


class DocumentAnalysisModelOutput(BaseModel):
    """What the model produces for one document (core schema, every profile)."""

    document_type_guess: str = Field(description='e.g. "incident ticket", "news article"')
    summary: str = Field(description="3 to 5 sentences")
    main_topics: list[str] = Field(description="3 to 6 short topics")
    key_entities: list[Entity]
    notable_points: list[NotablePoint]


class PageNote(BaseModel):
    """A page-cited note produced in the map step of map-reduce."""

    page: int
    note: str


class ChunkNotes(BaseModel):
    """Map-step output for one group of pages of a long document."""

    notes: list[PageNote]


# --------------------------------------------------------------------------- API output


class DocumentAnalysis(BaseModel):
    """Per-document result (CLAUDE.md section 8).

    ``incident`` is set for the incident profile (M6). ``statistical`` and
    ``triage`` arrive with the statistical profile (M8) and triage (M7).
    """

    document_id: str
    filename: str
    page_count: int
    profile: Profile
    document_type_guess: str
    summary: str
    main_topics: list[str]
    key_entities: list[Entity]
    notable_points: list[NotablePoint]
    visual_elements: list[VisualElement]
    warnings: list[DocumentWarning]
    incident: IncidentExtension | None = None
