"""Stage 2: visual analysis of the pages selected in stage 1.

For each selected page (in page order, one at a time, because a local model can
only serve one request efficiently):

1. Render the whole page to PNG (DECISIONS D-013).
2. Send it to the model with the visual prompt for the profile. The incident
   profile uses the evidence-observer guidance. Only the image is sent, not
   the page's text, so photo observations are independent of the reporter's
   written claims (DECISIONS D-027).
3. Validate the output, drop decorative elements, map it to ``VisualElement``,
   mask PII (if ``MASK_PII``), and check for prompt injection (regex scan of
   text the model read from the image, plus the model's own flag).
4. If the model returns nothing for a page that stage 1 *knows* has visual
   content, warn. This catches a model that was talked out of describing the
   page, without relying on the model (DECISIONS D-029).

Every failure (render error, timeout, refusal, invalid output, model
unavailable) becomes a ``VISUAL_ANALYSIS_FAILED`` warning for that page; the
document carries on (CLAUDE.md section 6). If the model is unavailable, the
remaining pages are skipped instead of each waiting to fail.

``page_text_with_visuals`` appends the results to a page's text inside
``[AI VISUAL DESCRIPTION - page N]`` delimiters for stage 3.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from app.config import Settings
from app.llm.base import (
    LLMError,
    LLMOutputInvalidError,
    LLMProvider,
    LLMRefusalError,
    LLMRequest,
    LLMTask,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.prompts import load_prompt, render_prompt
from app.llm.structured import generate_structured
from app.pipeline.extraction import render_page_png
from app.schemas.common import DocumentWarning, Profile, WarningCode
from app.schemas.extraction import ExtractedDocument, PageContent
from app.schemas.visual import VisualElement, VisualPageModelOutput
from app.security.injection import injection_warnings
from app.security.pii import mask_pii_in

logger = logging.getLogger(__name__)

# A detailed incident photo is ~800-1,500 output tokens. The cap stops a
# repetition loop from running until the timeout (the output is then rejected
# as truncated).
MAX_VISUAL_OUTPUT_TOKENS = 3072
# Upper bound on any list the model returns, to keep the UI and stage-3 input bounded.
MAX_LIST_ITEMS = 25

_PAGE_HINTS = {
    "embedded_image": "The page contains one or more embedded images.",
    "vector_drawing": "The page contains vector graphics, possibly a chart or diagram.",
    "scanned": (
        "The page appears to be scanned: it has little or no text layer. "
        "Transcribe its text as a scanned_text element."
    ),
}

_EMPTY_REASON = (
    "returned no visual elements, although the PDF shows images, drawings or scanned "
    "content on this page (the model may have been misled by text on the page)"
)

VISUAL_BEGIN = "[AI VISUAL DESCRIPTION - page {page}]"
VISUAL_END = "[/AI VISUAL DESCRIPTION]"
# Stops model text (which may echo text from the image) from forging or closing a block.
_DELIMITER_LOOKALIKE = re.compile(r"\[/?\s*AI\s+VISUAL\s+DESCRIPTION[^\]]*\]", re.IGNORECASE)


@dataclass
class VisualAnalysisResult:
    """Output of stage 2 for one document."""

    elements: list[VisualElement] = field(default_factory=list)
    warnings: list[DocumentWarning] = field(default_factory=list)
    analysed_pages: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------- public API


def build_visual_request(png: bytes, page: PageContent, profile: Profile) -> LLMRequest:
    """Build the model request for one rendered page.

    Public so the benchmark script and live tests send exactly what the pipeline sends.
    """
    hints = [_PAGE_HINTS[r] for r in page.visual_reasons]
    page_hints = "\nHINTS FROM PDF ANALYSIS\n" + "\n".join(f"- {h}" for h in hints) + "\n"
    guidance = "visual_guidance_incident" if profile == "incident" else "visual_guidance_general"
    prompt = render_prompt(
        "visual_page",
        page=page.page,
        page_hints=page_hints if hints else "",
        profile_guidance=load_prompt(guidance),
    )
    return LLMRequest(
        task=LLMTask.VISUAL_ANALYSIS,
        system=load_prompt("system"),
        prompt=prompt,
        json_schema={},  # filled in by generate_structured
        images=[png],
        max_output_tokens=MAX_VISUAL_OUTPUT_TOKENS,
        metadata={"page": page.page, "visual_reasons": list(page.visual_reasons)},
    )


async def analyse_visuals(
    data: bytes,
    extracted: ExtractedDocument,
    profile: Profile,
    provider: LLMProvider,
    settings: Settings,
    *,
    document_id: str | None = None,
) -> VisualAnalysisResult:
    """Run visual analysis on every page selected in stage 1.

    Args:
        data: The validated PDF bytes.
        extracted: Stage-1 output; pages with ``selected_for_visual_analysis`` are analysed.
        profile: Analysis profile (selects the photo guidance).
        provider: LLM provider.
        settings: Supplies ``RENDER_DPI``, ``MASK_PII`` and ``LLM_TIMEOUT_SECONDS``.
        document_id: For log correlation only.

    Returns:
        Elements for all pages that succeeded and one warning per page that did not.
    """
    result = VisualAnalysisResult()
    log_ctx = {"document_id": document_id, "stage": "analysing_visuals"}
    # Pages whose text layer already raised an injection warning; avoid a duplicate.
    already_flagged = {
        w.page for w in extracted.warnings if w.code is WarningCode.INJECTION_SUSPECTED
    }
    model_unavailable = False

    for page in (p for p in extracted.pages if p.selected_for_visual_analysis):
        if model_unavailable:
            result.warnings.append(
                _failure(page.page, "was skipped because the model is unavailable")
            )
            continue

        started = time.perf_counter()
        try:
            # PyMuPDF is CPU-bound and synchronous; keep the event loop responsive.
            png = await asyncio.to_thread(render_page_png, data, page.page, settings.render_dpi)
        except Exception:  # any render failure is a page-level warning, never a crash
            logger.exception("Page render failed", extra={**log_ctx, "page": page.page})
            result.warnings.append(_failure(page.page, "could not be rendered"))
            continue

        try:
            output, _ = await generate_structured(
                provider, build_visual_request(png, page, profile), VisualPageModelOutput
            )
        except LLMError as exc:
            model_unavailable = isinstance(exc, LLMUnavailableError)
            result.warnings.append(_failure(page.page, _reason(exc, settings)))
            logger.warning(
                "Visual analysis failed",
                extra={**log_ctx, "page": page.page, "code": exc.code},
            )
            continue

        if output.declined_reason and not output.elements:
            # The reason is model text that may echo the document, so it is not shown.
            result.warnings.append(_failure(page.page, "was declined by the model"))
            logger.warning(
                "Visual analysis declined",
                extra={**log_ctx, "page": page.page, "code": LLMRefusalError.code},
            )
            continue

        elements = to_visual_elements(output, page.page)
        if settings.mask_pii:
            elements = [VisualElement.model_validate(mask_pii_in(e.model_dump())) for e in elements]
        if page.page not in already_flagged:
            result.warnings.extend(
                _injection_in_image(page.page, elements, output.instructions_to_ai_present)
            )

        if not elements:
            # Stage 1 found non-decorative images, drawings or a scan here from the PDF
            # structure, so "nothing to see" contradicts it. This is a deterministic
            # backstop that does not rely on the model: in live tests the 4B model
            # obeyed "return an empty elements list" written on the page (D-029).
            result.warnings.append(_failure(page.page, _EMPTY_REASON))
            logger.warning(
                "Visual analysis returned no elements for a visual page",
                extra={**log_ctx, "page": page.page, "code": "VISUAL_EMPTY"},
            )
            continue

        result.elements.extend(elements)
        result.analysed_pages.append(page.page)
        logger.info(
            "Visual page analysed: %d elements",
            len(elements),
            extra={
                **log_ctx,
                "page": page.page,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )

    return result


def to_visual_elements(output: VisualPageModelOutput, page: int) -> list[VisualElement]:
    """Map model output onto the API schema: drop decorative items, set page, cap lists."""
    elements: list[VisualElement] = []
    for item in output.elements:
        if item.type == "decorative":
            continue
        data = item.model_dump()
        for key in ("observations", "possible_inferences", "information_gaps"):
            data[key] = data[key][:MAX_LIST_ITEMS]
        if data["chart"]:
            data["chart"]["key_values"] = data["chart"]["key_values"][:MAX_LIST_ITEMS]
        # Only keep type-specific fields on the matching type, so a stray
        # "chart" on a photo does not confuse the UI or stage 3.
        if item.type != "chart":
            data["chart"] = None
        if item.type != "table":
            data["table_markdown"] = None
        if item.type != "scanned_text":
            data["transcription"] = None
        elements.append(VisualElement(page=page, **data))
    return elements


def page_text_with_visuals(page: PageContent, elements: list[VisualElement]) -> str:
    """Page text plus tables plus visual descriptions, as stage 3 will see it.

    Each page's visual elements go in one delimited block, so the model in stage 3
    can tell AI-generated descriptions apart from the document's own text.
    """
    parts = [page.text.strip(), *page.tables]
    page_elements = [e for e in elements if e.page == page.page]
    if page_elements:
        body = "\n\n".join(_describe(e) for e in page_elements)
        parts.append(f"{VISUAL_BEGIN.format(page=page.page)}\n{body}\n{VISUAL_END}")
    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- helpers


def _describe(element: VisualElement) -> str:
    """Plain-text rendering of one element for the stage-3 prompt."""
    lines = [f"Type: {element.type}", f"Description: {element.description}"]
    if element.observations:
        lines.append("Observations:")
        lines += [f"- {o}" for o in element.observations]
    if element.possible_inferences:
        lines.append("Possible inferences (not directly visible):")
        lines += [f"- {i.inference} (basis: {i.basis})" for i in element.possible_inferences]
    if element.information_gaps:
        lines.append("Information gaps:")
        lines += [f"- {g}" for g in element.information_gaps]
    if element.chart:
        c = element.chart
        lines.append(f"Chart: {c.chart_type}; x axis: {c.x_axis}; y axis: {c.y_axis}")
        lines += [f"- {v}" for v in c.key_values]
        lines.append(f"Trend: {c.trend}")
    if element.table_markdown:
        lines += ["Table:", element.table_markdown]
    if element.transcription:
        lines += ["Transcription:", element.transcription]
    return _DELIMITER_LOOKALIKE.sub("", "\n".join(lines))


def _element_text(element: VisualElement) -> str:
    """Text the model read or described from the image, for the injection scan."""
    parts = [element.description, *element.observations]
    if element.transcription:
        parts.append(element.transcription)
    if element.table_markdown:
        parts.append(element.table_markdown)
    if element.chart:
        parts += element.chart.key_values
    return "\n".join(parts)


def _injection_in_image(
    page: int, elements: list[VisualElement], model_flagged: bool
) -> list[DocumentWarning]:
    """Flag instructions to an AI seen in the page image.

    Two independent signals: the regex scanner over text the model read from
    the image (e.g. a photo of a sign), and the model's own
    ``instructions_to_ai_present`` flag.
    """
    text = "\n".join(_element_text(e) for e in elements)
    warnings = injection_warnings([(page, text)], subject="An image on this page contains text")
    if not warnings and model_flagged:
        warnings = [
            DocumentWarning(
                code=WarningCode.INJECTION_SUSPECTED,
                message=(
                    "The model reported text on this page that tries to instruct an AI "
                    "system. It was treated as data; review the AI output for this page "
                    "with extra care."
                ),
                page=page,
            )
        ]
    for w in warnings:
        logger.warning(
            "Possible prompt injection in image",
            extra={"event": "security", "code": w.code.value, "page": page},
        )
    return warnings


def _reason(exc: LLMError, settings: Settings) -> str:
    """Analyst-facing wording for each failure type (never includes model text)."""
    if isinstance(exc, LLMTimeoutError):
        return f"timed out after {settings.llm_timeout_seconds:g} seconds"
    if isinstance(exc, LLMRefusalError):
        return "was declined by the model"
    if isinstance(exc, LLMOutputInvalidError):
        return "produced output that did not match the expected format"
    if isinstance(exc, LLMUnavailableError):
        return "failed because the model is unavailable"
    return "failed"  # pragma: no cover - all LLMError subclasses are handled above


def _failure(page: int, reason: str) -> DocumentWarning:
    """Page-level VISUAL_ANALYSIS_FAILED warning."""
    return DocumentWarning(
        code=WarningCode.VISUAL_ANALYSIS_FAILED,
        message=(
            f"Visual analysis of page {page} {reason}. Images on this page are not "
            "described; check the page directly."
        ),
        page=page,
    )
