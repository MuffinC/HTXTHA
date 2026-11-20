"""Shared schema types used across pipeline stages and API responses."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WarningCode(StrEnum):
    """Non-fatal problems attached to a document result and shown in the UI."""

    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    ACTIVE_CONTENT = "ACTIVE_CONTENT"  # only when ACTIVE_CONTENT_POLICY=warn
    VISUAL_PAGES_CAPPED = "VISUAL_PAGES_CAPPED"
    TABLE_EXTRACTION_FAILED = "TABLE_EXTRACTION_FAILED"
    VISUAL_ANALYSIS_FAILED = "VISUAL_ANALYSIS_FAILED"  # used from M2


class DocumentWarning(BaseModel):
    """A warning about a document, optionally tied to a page.

    Called ``Warning`` in CLAUDE.md section 8. The Python class is named
    ``DocumentWarning`` so it does not shadow the built-in ``Warning``, and the
    JSON schema title stays ``Warning`` to match the spec.
    """

    model_config = ConfigDict(title="Warning")

    code: WarningCode
    message: str
    page: int | None = Field(default=None, ge=1, description="1-based page number, if any")
