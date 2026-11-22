"""LLM provider interface shared by the Ollama and mock implementations.

The pipeline only talks to ``LLMProvider``. A provider is a *transport*: it
sends one request and returns the raw text plus call metadata. Parsing,
schema validation, refusal detection and retries live in
``app.llm.structured``, so they behave identically for every provider (and the
mock exercises the same code path as the real model).

Errors are typed so callers can turn them into page- or document-level
warnings instead of crashing (CLAUDE.md section 6).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class LLMTask(StrEnum):
    """What a request is for. The mock provider dispatches on this; Ollama ignores it."""

    VISUAL_ANALYSIS = "visual_analysis"
    DOCUMENT_ANALYSIS = "document_analysis"
    CHUNK_NOTES = "chunk_notes"  # map step of map-reduce for long documents
    CONSOLIDATION = "consolidation"
    INCIDENT_EXTRACTION = "incident_extraction"  # incident profile: facts for code rules
    TRIAGE = "triage"  # incident profile: may only raise the rule-based priority


@dataclass(frozen=True)
class LLMRequest:
    """One model call.

    Attributes:
        task: Purpose of the call (used by the mock and for logging).
        system: System prompt.
        prompt: User message. Untrusted content inside it must already be
            wrapped with ``app.security.boundary.wrap_untrusted``.
        json_schema: JSON schema the output must follow (Ollama ``format``).
        images: Raw PNG/JPEG bytes attached to the user message.
        max_output_tokens: Hard cap on generated tokens. Stops a repetition loop
            from running until the timeout.
        metadata: Facts about the request (page numbers, filename, first
            sentences of each page) that let the mock produce input-derived
            output. Never sent to the model and never logged.
    """

    task: LLMTask
    system: str
    prompt: str
    json_schema: dict[str, Any]
    images: list[bytes] = field(default_factory=list)
    max_output_tokens: int = 4096
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResult:
    """Raw provider response plus metadata for logging and benchmarks."""

    text: str
    model: str
    duration_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    # "stop" = finished normally; "length" = hit max_output_tokens (output is truncated).
    done_reason: str | None = None


# --------------------------------------------------------------------------- errors


class LLMError(Exception):
    """Base class. ``code`` is a stable string used in warnings and logs."""

    code = "LLM_ERROR"


class LLMUnavailableError(LLMError):
    """Ollama is unreachable, the model is not pulled, or the server returned an error."""

    code = "LLM_UNAVAILABLE"


class LLMTimeoutError(LLMError):
    """The call exceeded ``LLM_TIMEOUT_SECONDS``."""

    code = "LLM_TIMEOUT"


class LLMOutputInvalidError(LLMError):
    """The output was truncated, not JSON, or did not validate against the schema.

    ``validation_errors`` holds location + message pairs (never the offending
    values) so a retry prompt can tell the model what to fix.
    """

    code = "LLM_OUTPUT_INVALID"

    def __init__(self, message: str, validation_errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.validation_errors = validation_errors or []


class LLMRefusalError(LLMError):
    """The model declined to analyse the content."""

    code = "LLM_REFUSED"


# --------------------------------------------------------------------------- interface


class LLMProvider(ABC):
    """A source of model completions."""

    #: Value reported as ``provider`` by ``/api/health``.
    name: Literal["ollama", "mock"]
    #: Model identifier reported by ``/api/health`` and written to logs.
    model: str

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResult:
        """Run one request and return the raw output.

        Raises:
            LLMUnavailableError: The backend cannot serve the request.
            LLMTimeoutError: The call took longer than the configured timeout.
        """

    @abstractmethod
    async def is_ready(self) -> bool:
        """Return True if the provider can serve requests now (used by ``/api/health``).

        Must not raise and must return quickly: the frontend polls it.
        """
