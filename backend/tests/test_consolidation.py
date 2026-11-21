"""Tests for stage 4 (consolidated report): D-labels, citation checks, retry."""

import json
from typing import Any

import pytest

from app.config import Settings
from app.llm.base import LLMOutputInvalidError, LLMTask
from app.pipeline.consolidation import consolidate
from app.schemas.analysis import DocumentAnalysis, NotablePoint
from app.schemas.common import WarningCode
from tests.llm_fakes import RecordingProvider

ID_A = "aaaaaaaa-0000-4000-8000-000000000001"
ID_B = "bbbbbbbb-0000-4000-8000-000000000002"


def _analysis(document_id: str, page_count: int, summary: str) -> DocumentAnalysis:
    return DocumentAnalysis(
        document_id=document_id,
        filename=f"{document_id}.pdf",
        page_count=page_count,
        profile="general",
        document_type_guess="incident report",
        summary=summary,
        main_topics=["collision"],
        key_entities=[],
        notable_points=[NotablePoint(point="A point.", page=1)],
        visual_elements=[],
        warnings=[],
    )


DOCS = [_analysis(ID_A, 2, "Report A."), _analysis(ID_B, 1, "Report B.")]


def _cite(document: str, page: int = 1) -> dict[str, Any]:
    return {"document": document, "page": page}


def _output(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "overall_summary": "Both describe a collision.",
        "common_themes": [],
        "agreements": [],
        "contradictions": [],
        "timeline": [],
        "related_document_groups": [],
        "information_gaps": [],
    }
    return json.dumps(base | overrides)


async def test_prompt_uses_short_labels_not_uuids(settings: Settings) -> None:
    provider = RecordingProvider()
    await consolidate(DOCS, provider, settings)

    [request] = provider.calls(LLMTask.CONSOLIDATION)
    assert "Document D1 (2 pages)" in request.prompt
    assert "Document D2 (1 pages)" in request.prompt
    assert ID_A not in request.prompt and ID_B not in request.prompt
    assert "<<<UNTRUSTED_CONTENT_BEGIN id=" in request.prompt


async def test_labels_are_mapped_back_to_document_ids(settings: Settings) -> None:
    output = _output(
        agreements=[{"point": "Same junction.", "citations": [_cite("D1", 2), _cite("d2")]}],
        related_document_groups=[{"documents": ["D1", "Document D2"], "reason": "Same event."}],
    )
    report = await consolidate(DOCS, RecordingProvider({LLMTask.CONSOLIDATION: [output]}), settings)

    [agreement] = report.agreements
    assert [(c.document_id, c.page) for c in agreement.citations] == [(ID_A, 2), (ID_B, 1)]
    assert report.related_document_groups[0].document_ids == [ID_A, ID_B]
    assert report.warnings == []


async def test_invalid_citations_are_removed_counted_and_flagged(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    output = _output(
        common_themes=[
            {"theme": "kept", "citations": [_cite("D1"), _cite("D9")]},  # D9 does not exist
            {"theme": "dropped", "citations": [_cite("D2", 5)]},  # D2 has 1 page
        ],
        contradictions=[
            {
                "topic": "time",
                "positions": [
                    {"position": "21:15", "citation": _cite("D1")},
                    {"position": "21:30", "citation": _cite("D2", 3)},  # invalid page
                ],
            }
        ],
        related_document_groups=[{"documents": ["D1", "D7"], "reason": "x"}],
    )
    with caplog.at_level("WARNING"):
        report = await consolidate(
            DOCS, RecordingProvider({LLMTask.CONSOLIDATION: [output]}), settings
        )

    assert [t.theme for t in report.common_themes] == ["kept"]
    assert report.contradictions == []  # one valid position is not a contradiction
    assert report.related_document_groups == []  # one valid document is not a group
    [warning] = report.warnings
    assert warning.code is WarningCode.CITATIONS_REMOVED
    record = next(r for r in caplog.records if getattr(r, "event", None) == "citations_removed")
    assert record.count == 4  # type: ignore[attr-defined]


async def test_consolidation_retries_once_then_raises(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.CONSOLIDATION: ["{}", "{}"]})
    with pytest.raises(LLMOutputInvalidError):
        await consolidate(DOCS, provider, settings)
    assert len(provider.calls(LLMTask.CONSOLIDATION)) == 2


async def test_masking_never_touches_document_ids(settings: Settings) -> None:
    # Regression (D-053): this UUID's last segment contains "96609844", which looks
    # like a Singapore phone number. Masking the final report used to corrupt it.
    phone_like_id = "a75d14ec-072e-4838-84d5-cb96609844e7"
    docs = [_analysis(ID_A, 2, "Report A."), _analysis(phone_like_id, 1, "Report B.")]
    output = _output(
        overall_summary="Witness phone 9123 4567 is in report B.",
        related_document_groups=[{"documents": ["D1", "D2"], "reason": "Same event."}],
    )
    report = await consolidate(docs, RecordingProvider({LLMTask.CONSOLIDATION: [output]}), settings)

    assert report.related_document_groups[0].document_ids == [ID_A, phone_like_id]
    assert "9123 4567" not in report.overall_summary  # text is still masked
