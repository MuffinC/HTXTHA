"""Pydantic models for the API error envelope (CLAUDE.md section 7)."""

from typing import Any

from pydantic import BaseModel, Field

from app.errors import ErrorCode


class ErrorBody(BaseModel):
    """The ``error`` object inside the envelope."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """``{"error": {code, message, details}}`` returned for every API error."""

    error: ErrorBody
