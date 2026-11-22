"""Results of upload-time file validation (pipeline stage 0)."""

from pydantic import BaseModel, Field

from app.errors import ErrorCode
from app.schemas.common import DocumentWarning


class AcceptedFile(BaseModel):
    """A file that passed validation and may be queued for processing."""

    filename: str = Field(description="Sanitised filename, for display only")
    size_bytes: int
    page_count: int
    warnings: list[DocumentWarning] = Field(default_factory=list)
    #: Where ``%PDF-`` starts. Bytes before it are dropped before storage (D-074).
    header_offset: int = 0


class RejectedFile(BaseModel):
    """A file that failed validation. Matches the ``rejected[]`` items of ``POST /jobs``."""

    filename: str = Field(description="Sanitised filename, for display only")
    code: ErrorCode
    message: str


FileValidationResult = AcceptedFile | RejectedFile
