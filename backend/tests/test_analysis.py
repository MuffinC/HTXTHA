"""Tests for stage 3 (document analysis): prompt, citations, retry, map-reduce."""

import json
import re
from typing import Any

import pytest

from app.config import Settings
from app.errors import ErrorCode
from app.llm.base import LLMTask, LLMTimeoutError
from app.pipeline.analysis import DocumentFailure, analyse_document
from app.pipeline.extraction import extract_document
from app.schemas.common import WarningCode
from app.schemas.visual import VisualElement
from tests import pdf_factory
from tests.llm_fakes import RecordingProvider

DOC_ID = "6f1c2a8e-0000-4000-8000-000000000001"


def _output(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "document_type_guess": "incident report",
        "summary": "Two cars collided at a junction.",
        "main_topics": ["collision"],
        "key_entities": [{"name": "community centre", "type": "location", "pages": [1]}],
        "notable_points": [{"point": "The light was green.", "page": 1}],
    }
    return json.dumps(base | overrides)


async def _analyse(
    data: bytes,
    provider: RecordingProvider,
    settings: Settings,
    visual_elements: list[VisualElement] | None = None,
) -> Any:
    extracted = extract_document(data, settings)
    return await analyse_document(
        document_id=DOC_ID,
        filename="report.pdf",
        extracted=extracted,
        visual_elements=visual_elements or [],
        warnings=list(extracted.warnings),
        profile="general",
        provider=provider,
        settings=settings,
    )


# --------------------------------------------------------------------------- prompt


async def test_document_text_is_wrapped_in_random_boundary(settings: Settings) -> None:
    provider = RecordingProvider()
    await _analyse(pdf_factory.valid_text_pdf(pages=2), provider, settings)

    [request] = provider.calls(LLMTask.DOCUMENT_ANALYSIS)
    begin = re.search(r"<<<UNTRUSTED_CONTENT_BEGIN id=([0-9a-f]{16})>>>", request.prompt)
    assert begin, "document text must be wrapped"
    boundary = begin.group(1)
    end = request.prompt.index(f"<<<UNTRUSTED_CONTENT_END id={boundary}>>>")
    inside = request.prompt[begin.end() : end]
    assert "--- Page 1 ---" in inside and "--- Page 2 ---" in inside
    assert f"id={boundary}" in request.prompt.split("<<<")[0]  # named in the instructions
    assert "report.pdf" not in request.prompt  # the filename is not sent


async def test_visual_descriptions_are_included_with_delimiters(settings: Settings) -> None:
    provider = RecordingProvider()
    photo = VisualElement(page=1, type="photo", description="A dented blue car.")
    await _analyse(pdf_factory.photo_pdf(), provider, settings, visual_elements=[photo])

    prompt = provider.calls(LLMTask.DOCUMENT_ANALYSIS)[0].prompt
    assert "[AI VISUAL DESCRIPTION - page 1]" in prompt
    assert "A dented blue car." in prompt


async def test_result_combines_pipeline_and_model_fields(settings: Settings) -> None:
    result = await _analyse(pdf_factory.valid_text_pdf(pages=2), RecordingProvider(), settings)

    assert result.document_id == DOC_ID
    assert result.filename == "report.pdf"
    assert result.page_count == 2
    assert result.profile == "general"
    assert result.summary.startswith("[MOCK]")
    assert all(1 <= p.page <= 2 for p in result.notable_points)


# --------------------------------------------------------------------------- citations


async def test_citations_to_missing_pages_are_removed_and_flagged(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    output = _output(
        key_entities=[
            {"name": "junction", "type": "location", "pages": [1, 7, 1]},
            {"name": "ghost", "type": "other", "pages": [9]},
        ],
        notable_points=[{"point": "real", "page": 1}, {"point": "invented", "page": 4}],
    )
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [output]})
    with caplog.at_level("WARNING"):
        result = await _analyse(pdf_factory.valid_text_pdf(), provider, settings)

    assert [(e.name, e.pages) for e in result.key_entities] == [("junction", [1])]
    assert [p.point for p in result.notable_points] == ["real"]
    [warning] = [w for w in result.warnings if w.code is WarningCode.CITATIONS_REMOVED]
    assert warning.message.startswith("3 citation(s)")
    record = next(r for r in caplog.records if getattr(r, "event", None) == "citations_removed")
    assert record.count == 3  # type: ignore[attr-defined]


async def test_valid_citations_produce_no_warning(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [_output()]})
    result = await _analyse(pdf_factory.valid_text_pdf(), provider, settings)
    assert not [w for w in result.warnings if w.code is WarningCode.CITATIONS_REMOVED]


# --------------------------------------------------------------------------- failures


async def test_invalid_output_is_retried_once_then_fails(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: ["{}", '{"summary": 1}']})

    with pytest.raises(DocumentFailure) as info:
        await _analyse(pdf_factory.valid_text_pdf(), provider, settings)

    assert info.value.code is ErrorCode.LLM_OUTPUT_INVALID
    calls = provider.calls(LLMTask.DOCUMENT_ANALYSIS)
    assert len(calls) == 2
    assert "did not match the required JSON schema" in calls[1].prompt


async def test_retry_can_recover(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: ["{}", _output()]})
    result = await _analyse(pdf_factory.valid_text_pdf(), provider, settings)
    assert result.summary == "Two cars collided at a junction."


async def test_timeout_fails_document_with_code(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [LLMTimeoutError("slow")]})
    with pytest.raises(DocumentFailure) as info:
        await _analyse(pdf_factory.valid_text_pdf(), provider, settings)
    assert info.value.code is ErrorCode.LLM_TIMEOUT


async def test_pii_masked_in_analysis(settings: Settings) -> None:
    output = _output(summary="Call the reporter on 9123 4567 (NRIC S1234567D).")
    result = await _analyse(
        pdf_factory.valid_text_pdf(),
        RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [output]}),
        settings,
    )
    assert "9123 4567" not in result.summary and "S1234567D" not in result.summary


# --------------------------------------------------------------------------- map-reduce


async def test_long_document_uses_map_reduce(make_settings: Any) -> None:
    # 3 pages of ~1,300 chars (~450 estimated tokens each). With num_ctx 4700 the
    # single-pass budget is 128 tokens and a notes chunk holds 2 pages.
    settings = make_settings(ollama_num_ctx=4700)
    provider = RecordingProvider()

    result = await _analyse(pdf_factory.long_text_pdf(3), provider, settings)

    chunks = provider.calls(LLMTask.CHUNK_NOTES)
    assert [(c.metadata["first_page"], c.metadata["last_page"]) for c in chunks] == [(1, 2), (3, 3)]
    for chunk in chunks:
        assert "<<<UNTRUSTED_CONTENT_BEGIN id=" in chunk.prompt
    [final] = provider.calls(LLMTask.DOCUMENT_ANALYSIS)
    assert "given as notes" in final.prompt
    assert "(p.3) [MOCK] Note for page 3." in final.prompt
    assert "--- Page 1 ---" not in final.prompt  # raw text is not sent in the reduce step
    assert result.page_count == 3


async def test_notes_citing_pages_outside_their_chunk_are_dropped(make_settings: Any) -> None:
    settings = make_settings(ollama_num_ctx=4700)
    bad_notes = json.dumps({"notes": [{"page": 1, "note": "ok"}, {"page": 3, "note": "wrong"}]})
    provider = RecordingProvider({LLMTask.CHUNK_NOTES: [bad_notes]})

    result = await _analyse(pdf_factory.long_text_pdf(3), provider, settings)

    final = provider.calls(LLMTask.DOCUMENT_ANALYSIS)[0].prompt
    assert "(p.1) ok" in final and "wrong" not in final
    assert any(w.code is WarningCode.CITATIONS_REMOVED for w in result.warnings)


async def test_oversized_page_is_truncated_with_warning(make_settings: Any) -> None:
    # ~3,900 chars per page (~1,300 tokens) is more than one notes chunk (1,152).
    settings = make_settings(ollama_num_ctx=4700)
    result = await _analyse(
        pdf_factory.long_text_pdf(2, sentences_per_page=60), RecordingProvider(), settings
    )
    truncated = [w for w in result.warnings if w.code is WarningCode.CONTENT_TRUNCATED]
    assert [w.page for w in truncated] == [1, 2]


async def test_short_document_uses_single_pass(settings: Settings) -> None:
    provider = RecordingProvider()
    await _analyse(pdf_factory.long_text_pdf(3), provider, settings)  # default 16k context
    assert provider.calls(LLMTask.CHUNK_NOTES) == []


async def test_entities_that_are_only_a_masked_value_are_dropped(settings: Settings) -> None:
    # Live run (L-015): a contact number listed as a person became "[PHONE REDACTED]".
    output = _output(
        key_entities=[
            {"name": "9123 4567", "type": "person_role", "pages": [1]},
            {"name": "Driver on 9123 4567", "type": "person_role", "pages": [1]},
            {"name": "community centre", "type": "location", "pages": [1]},
        ]
    )
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [output]})
    result = await _analyse(pdf_factory.valid_text_pdf(), provider, settings)
    assert [e.name for e in result.key_entities] == [
        "Driver on [PHONE REDACTED]",
        "community centre",
    ]
