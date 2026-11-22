"""Stage 3: analyse one document into the core schema (CLAUDE.md section 6).

Input is each page's text, its tables, and the AI visual descriptions from
stage 2 (inside ``[AI VISUAL DESCRIPTION]`` blocks), with a ``--- Page N ---``
heading per page so the model can cite pages. All of it is wrapped in the
random-boundary markers (``app.security.boundary``) because it is untrusted.

If the content does not fit the context budget, map-reduce is used:

* **map**: consecutive pages are grouped into chunks that fit, and the model
  writes page-cited notes for each chunk (``ChunkNotes``);
* **reduce**: the analysis runs over the notes instead of the raw text.

Output is validated with Pydantic and retried once with the validation errors
(spec section 6). It is then citation-checked against the real page count and
PII-masked (if ``MASK_PII``). Model errors raise ``DocumentFailure`` with a
stable code; the worker marks the document ``failed`` and the job carries on.
"""

import logging
import re
import time

from app.config import Settings
from app.errors import ErrorCode
from app.llm.base import (
    LLMError,
    LLMOutputInvalidError,
    LLMProvider,
    LLMRefusalError,
    LLMRequest,
    LLMTask,
    LLMTimeoutError,
)
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline.budget import content_budget_tokens, estimate_tokens, truncate_to_tokens
from app.pipeline.citations import is_valid_page, removed_citations_warning
from app.pipeline.incident import extract_incident
from app.pipeline.visual import page_text_with_visuals
from app.schemas.analysis import (
    ChunkNotes,
    DocumentAnalysis,
    DocumentAnalysisModelOutput,
    PageNote,
)
from app.schemas.common import DocumentWarning, Profile, WarningCode
from app.schemas.extraction import ExtractedDocument
from app.schemas.visual import VisualElement
from app.security.boundary import wrap_untrusted
from app.security.pii import is_only_mask, mask_pii_in

logger = logging.getLogger(__name__)

ANALYSIS_OUTPUT_TOKENS = 3072
NOTES_OUTPUT_TOKENS = 2048
MAX_NOTES_PER_CHUNK = 15
# Stage 3 retries once on invalid output (spec section 6).
ANALYSIS_RETRIES = 1

_FULL_TEXT = 'Each page starts with a heading "--- Page N ---".'
_NOTES = (
    "The document was too long to analyse in one pass, so it is given as notes written "
    'from each part of it. Each note starts with the page it comes from, written "(p.N)".'
)


class DocumentFailure(Exception):
    """The document could not be analysed. ``message`` is written by us, never the model."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def analyse_document(
    *,
    document_id: str,
    filename: str,
    extracted: ExtractedDocument,
    visual_elements: list[VisualElement],
    warnings: list[DocumentWarning],
    profile: Profile,
    provider: LLMProvider,
    settings: Settings,
) -> DocumentAnalysis:
    """Run stage 3 for one document.

    Args:
        document_id: Generated document ID.
        filename: Sanitised display filename (not sent to the model).
        extracted: Stage-1 output.
        visual_elements: Stage-2 output, merged into the page text.
        warnings: Warnings so far (upload, extraction, visual); returned with any new ones.
        profile: Analysis profile.
        provider: LLM provider.
        settings: Context size, PII masking.

    Raises:
        DocumentFailure: The model failed, timed out, refused, or its output was
            still invalid after one retry.
    """
    warnings = list(warnings)
    page_count = extracted.page_count
    pages = [
        (
            p.page,
            f"--- Page {p.page} ---\n{page_text_with_visuals(p, visual_elements) or '(no text)'}",
        )
        for p in extracted.pages
    ]
    budget = content_budget_tokens(settings.ollama_num_ctx, ANALYSIS_OUTPUT_TOKENS)
    full_text = "\n\n".join(text for _, text in pages)
    mock_meta = {
        "page_count": page_count,
        "first_sentences": {p.page: _first_sentence(p.text) for p in extracted.pages},
        # Full page text, for the mock provider's keyword-based incident extraction.
        "page_texts": {p.page: p.text for p in extracted.pages},
    }

    try:
        if estimate_tokens(full_text) <= budget:
            content, description = full_text, _FULL_TEXT
        else:
            notes = await _map_notes(pages, page_count, provider, settings, warnings, mock_meta)
            content, description = _notes_content(notes, budget, warnings), _NOTES
        output = await _analyse(content, description, page_count, profile, provider, mock_meta)
    except LLMError as exc:
        raise _failure(exc, settings) from exc

    incident = None
    if profile == "incident":
        try:
            incident, incident_warnings = await extract_incident(
                content=content,
                content_description=description,
                page_count=page_count,
                visual_elements=visual_elements,
                provider=provider,
                settings=settings,
                mock_meta=mock_meta,
            )
            warnings.extend(incident_warnings)
        except LLMError as exc:
            # The core analysis is still useful; say clearly what is missing.
            logger.warning(
                "Incident extraction failed", extra={"stage": "analysing", "code": exc.code}
            )
            warnings.append(
                DocumentWarning(
                    code=WarningCode.INCIDENT_EXTRACTION_FAILED,
                    message="The incident facts (claims, consistency checks) could not be "
                    "extracted. The general analysis below is still available.",
                )
            )

    output = drop_artefact_items(output, extracted.boilerplate_lines, full_text)
    output, removed = clean_citations(output, page_count)
    warning = removed_citations_warning(removed, "this document's analysis")
    if warning:
        warnings.append(warning)
    if settings.mask_pii:
        output = DocumentAnalysisModelOutput.model_validate(mask_pii_in(output.model_dump()))
        # An entity that was only a phone number or NRIC is now just a placeholder:
        # noise in the entity list, so it is dropped (L-015).
        output = output.model_copy(
            update={
                "key_entities": [e for e in output.key_entities if not is_only_mask(e.name)],
                "main_topics": [t for t in output.main_topics if not is_only_mask(t)],
            }
        )

    return DocumentAnalysis(
        document_id=document_id,
        filename=filename,
        page_count=page_count,
        profile=profile,
        visual_elements=visual_elements,
        warnings=warnings,
        incident=incident,
        **output.model_dump(),
    )


def drop_artefact_items(
    output: DocumentAnalysisModelOutput, boilerplate_lines: list[str], source_text: str
) -> DocumentAnalysisModelOutput:
    """Drop items that are empty or come only from a removed header/footer line.

    Pipeline markers were already stripped from every string (``app.llm.artefacts``),
    which can leave an entity with no name ("AI VISUAL DESCRIPTION") or an empty
    point. Header/footer lines are taken out of the page text in stage 1, but the
    model can still see them in a rendered page image. So an entity or topic that
    occurs in a header/footer line and nowhere in the text the model was given
    (``source_text``) has only that line as its source, and is dropped. An
    organisation named in a running header *and* in the body is kept.
    """
    footers = [_normalise(line) for line in boilerplate_lines]
    source = _normalise(source_text)

    def from_boilerplate_only(name: str) -> bool:
        n = _normalise(name)
        return any(n in f or f in n for f in footers) and n not in source

    entities = [
        e for e in output.key_entities if e.name.strip() and not from_boilerplate_only(e.name)
    ]
    points = [p for p in output.notable_points if p.point.strip()]
    topics = [t for t in output.main_topics if t.strip() and not from_boilerplate_only(t)]
    return output.model_copy(
        update={"key_entities": entities, "notable_points": points, "main_topics": topics}
    )


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def clean_citations(
    output: DocumentAnalysisModelOutput, page_count: int
) -> tuple[DocumentAnalysisModelOutput, int]:
    """Drop page references outside ``1..page_count``.

    Entities keep their valid pages (deduplicated, sorted) and are dropped if
    none remain; notable points with an invalid page are dropped.

    Returns:
        The cleaned output and the number of citations removed.
    """
    removed = 0
    entities = []
    for entity in output.key_entities:
        valid = [p for p in entity.pages if is_valid_page(p, page_count)]
        removed += len(entity.pages) - len(valid)
        # An entity with no valid page is unverifiable, so it is dropped.
        if valid:
            entities.append(entity.model_copy(update={"pages": sorted(set(valid))}))
    points = [p for p in output.notable_points if is_valid_page(p.page, page_count)]
    removed += len(output.notable_points) - len(points)
    cleaned = output.model_copy(update={"key_entities": entities, "notable_points": points})
    return cleaned, removed


# --------------------------------------------------------------------------- model calls


# Incident reports record people by role, never by name (CLAUDE.md section 8).
_PROFILE_RULES = {
    "incident": "- This is an incident report: record people by ROLE only (for example "
    '"driver of the silver car"), never by name, even if the report names them.\n',
}


async def _analyse(
    content: str,
    description: str,
    page_count: int,
    profile: Profile,
    provider: LLMProvider,
    mock_meta: dict[str, object],
) -> DocumentAnalysisModelOutput:
    wrapped, boundary = wrap_untrusted(content)
    prompt = render_prompt(
        "document_analysis",
        page_count=page_count,
        content_description=description,
        boundary=boundary,
        content=wrapped,
        profile_rules=_PROFILE_RULES.get(profile, ""),
    )
    request = LLMRequest(
        task=LLMTask.DOCUMENT_ANALYSIS,
        system=load_prompt("system"),
        prompt=prompt,
        json_schema={},
        max_output_tokens=ANALYSIS_OUTPUT_TOKENS,
        metadata=mock_meta,
    )
    started = time.perf_counter()
    output, _ = await generate_structured(
        provider, request, DocumentAnalysisModelOutput, retries=ANALYSIS_RETRIES
    )
    logger.info(
        "Document analysis call finished",
        extra={"stage": "analysing", "duration_ms": _ms(started)},
    )
    return output


async def _map_notes(
    pages: list[tuple[int, str]],
    page_count: int,
    provider: LLMProvider,
    settings: Settings,
    warnings: list[DocumentWarning],
    mock_meta: dict[str, object],
) -> list[PageNote]:
    """Map step: page-cited notes for each chunk of pages that fits the budget."""
    budget = content_budget_tokens(settings.ollama_num_ctx, NOTES_OUTPUT_TOKENS)
    chunks = _chunk_pages(pages, budget, warnings)
    logger.info(
        "Document exceeds context budget; using map-reduce",
        extra={"stage": "analysing", "event": "map_reduce", "count": len(chunks)},
    )
    notes: list[PageNote] = []
    removed = 0
    for chunk in chunks:
        first, last = chunk[0][0], chunk[-1][0]
        wrapped, boundary = wrap_untrusted("\n\n".join(text for _, text in chunk))
        request = LLMRequest(
            task=LLMTask.CHUNK_NOTES,
            system=load_prompt("system"),
            prompt=render_prompt(
                "chunk_notes",
                first_page=first,
                last_page=last,
                page_count=page_count,
                boundary=boundary,
                content=wrapped,
                max_notes=MAX_NOTES_PER_CHUNK,
            ),
            json_schema={},
            max_output_tokens=NOTES_OUTPUT_TOKENS,
            metadata={**mock_meta, "first_page": first, "last_page": last},
        )
        result, _ = await generate_structured(provider, request, ChunkNotes, retries=1)
        # A note citing a page outside its own chunk cannot be right.
        kept = [n for n in result.notes if first <= n.page <= last][:MAX_NOTES_PER_CHUNK]
        removed += len(result.notes[:MAX_NOTES_PER_CHUNK]) - len(kept)
        notes.extend(kept)
    warning = removed_citations_warning(removed, "the notes made for this long document")
    if warning:
        warnings.append(warning)
    return notes


def _chunk_pages(
    pages: list[tuple[int, str]], budget: int, warnings: list[DocumentWarning]
) -> list[list[tuple[int, str]]]:
    """Group consecutive pages into chunks under ``budget`` tokens.

    A single page larger than the budget is truncated, with a warning.
    """
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    used = 0
    for page, text in pages:
        cost = estimate_tokens(text)
        if cost > budget:
            text = truncate_to_tokens(text, budget)
            cost = budget
            warnings.append(
                DocumentWarning(
                    code=WarningCode.CONTENT_TRUNCATED,
                    message=(
                        f"Page {page} has more text than the model can read at once; only "
                        "its beginning was analysed."
                    ),
                    page=page,
                )
            )
        if current and used + cost > budget:
            chunks.append(current)
            current, used = [], 0
        current.append((page, text))
        used += cost
    if current:
        chunks.append(current)
    return chunks


def _notes_content(notes: list[PageNote], budget: int, warnings: list[DocumentWarning]) -> str:
    """Format notes for the reduce step, dropping the tail if they still do not fit."""
    lines: list[str] = []
    used = 0
    for i, note in enumerate(notes):
        line = f"(p.{note.page}) {note.note}"
        cost = estimate_tokens(line) + 1
        if used + cost > budget:
            warnings.append(
                DocumentWarning(
                    code=WarningCode.CONTENT_TRUNCATED,
                    message=(
                        f"The document is very long; notes from page {note.page} onwards "
                        "did not fit and are not reflected in the analysis."
                    ),
                )
            )
            logger.warning(
                "Reduce input truncated",
                extra={"stage": "analysing", "event": "content_truncated", "count": len(notes) - i},
            )
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


# --------------------------------------------------------------------------- helpers

_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def _first_sentence(text: str) -> str:
    """First sentence of ``text`` (for the mock provider only)."""
    text = " ".join(text.split())
    return _SENTENCE_END.split(text, maxsplit=1)[0][:300] if text else ""


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _failure(exc: LLMError, settings: Settings) -> DocumentFailure:
    """Map a model error to a document-level failure with an analyst-facing message."""
    if isinstance(exc, LLMOutputInvalidError):
        return DocumentFailure(
            ErrorCode.LLM_OUTPUT_INVALID,
            "The model's analysis did not match the expected format, even after one retry.",
        )
    if isinstance(exc, LLMTimeoutError):
        return DocumentFailure(
            ErrorCode.LLM_TIMEOUT,
            f"The model did not finish within {settings.llm_timeout_seconds:g} seconds.",
        )
    if isinstance(exc, LLMRefusalError):
        return DocumentFailure(
            ErrorCode.LLM_REFUSED, "The model declined to analyse this document."
        )
    return DocumentFailure(
        ErrorCode.LLM_UNAVAILABLE, "The model is unavailable. Check that Ollama is running."
    )
