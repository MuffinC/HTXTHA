"""API schemas for jobs, documents and profiles (CLAUDE.md sections 6 and 9)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.analysis import DocumentAnalysis
from app.schemas.common import DocumentWarning, Profile
from app.schemas.consolidated import ConsolidatedReport
from app.schemas.validation import RejectedFile


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"  # every document analysed and the consolidated report built
    PARTIAL = "partial"  # some documents (or the consolidated report) failed
    FAILED = "failed"  # nothing usable was produced


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    ANALYSING_VISUALS = "analysing_visuals"
    ANALYSING = "analysing"
    COMPLETED = "completed"
    REJECTED = "rejected"  # failed upload validation (never processed)
    FAILED = "failed"  # failed during processing


class ErrorInfo(BaseModel):
    """Why a document or job failed. ``message`` is written by the backend, never the model."""

    code: str
    message: str


class AcceptedDocument(BaseModel):
    """An uploaded file that passed validation and was queued."""

    document_id: str
    filename: str
    page_count: int
    warnings: list[DocumentWarning]


class JobCreatedResponse(BaseModel):
    """Body of ``202`` from ``POST /api/jobs``."""

    job_id: str
    accepted: list[AcceptedDocument]
    rejected: list[RejectedFile]


class DocumentResult(BaseModel):
    """One document's progress and, once completed, its analysis."""

    document_id: str
    filename: str
    status: DocumentStatus
    page_count: int | None
    error: ErrorInfo | None = None
    analysis: DocumentAnalysis | None = None


class JobResponse(BaseModel):
    """Body of ``GET /api/jobs/{job_id}``."""

    job_id: str
    profile: Profile
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    error: ErrorInfo | None = None
    documents: list[DocumentResult]
    consolidated: ConsolidatedReport | None = None
    # Why there is no consolidated report: it needs two analysed documents, or it failed.
    consolidated_error: ErrorInfo | None = None


class ProfileInfo(BaseModel):
    """One entry of ``GET /api/profiles``."""

    id: Profile
    name: str
    description: str
    available: bool
