"""Error codes and the application exception type.

Every API error is returned in one envelope (CLAUDE.md section 7):

    {"error": {"code": "STRING_CODE", "message": "Human readable", "details": {...}}}

``ErrorCode`` is the single list of machine-readable codes. File-level codes
(e.g. ``ENCRYPTED_PDF``) also appear per file in upload responses, so the
frontend can map one code list to friendly messages.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Machine-readable error codes. Values equal names so they serialise cleanly."""

    # ---- File validation (CLAUDE.md section 7) ----
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    CORRUPT_PDF = "CORRUPT_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    ACTIVE_CONTENT = "ACTIVE_CONTENT"

    # ---- Document processing (per document, in GET /api/jobs/{id}) ----
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"  # still invalid after one retry (spec section 6)
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_REFUSED = "LLM_REFUSED"
    INTERRUPTED = "INTERRUPTED"  # backend restarted while the job was queued or running

    # ---- Generic request errors ----
    NO_VALID_FILES = "NO_VALID_FILES"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """An error that should reach the client as a structured envelope.

    Raise this from route handlers or services; the handler registered in
    ``app.api.errors`` converts it into the JSON envelope and HTTP status.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
