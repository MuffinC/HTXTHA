"""Mock provider: deterministic, schema-valid output with no model.

Lets the whole app run, demo and be tested on a machine without Ollama or a GPU
(CLAUDE.md principle 6). Output is derived from the request metadata (page
numbers, why a page needed visual analysis, the first sentence of each page,
the document labels), so the UI looks realistic, and it is
returned as JSON *text*, so it goes through the same parsing and validation as
real model output.

Every mock text starts with "[MOCK]" so it can never be mistaken for real analysis.
"""

import json
from typing import Any

from app.llm.base import LLMProvider, LLMRequest, LLMResult, LLMTask


class MockProvider(LLMProvider):
    """Returns canned output keyed on ``request.task``."""

    name = "mock"
    model = "mock"

    async def complete(self, request: LLMRequest) -> LLMResult:
        """Return deterministic JSON for the request's task."""
        builders = {
            LLMTask.VISUAL_ANALYSIS: _visual_output,
            LLMTask.DOCUMENT_ANALYSIS: _document_output,
            LLMTask.CHUNK_NOTES: _chunk_notes_output,
            LLMTask.CONSOLIDATION: _consolidation_output,
        }
        payload = builders[request.task](request.metadata)
        return LLMResult(
            text=json.dumps(payload),
            model=self.model,
            duration_ms=0,
            prompt_tokens=0,
            output_tokens=0,
            done_reason="stop",
        )

    async def is_ready(self) -> bool:
        """The mock needs no model, so it is always ready."""
        return True


def _visual_output(metadata: dict[str, Any]) -> dict[str, Any]:
    """One sample element whose type follows the page's extraction result."""
    page = metadata.get("page", 1)
    reasons = metadata.get("visual_reasons", [])

    if "vector_drawing" in reasons:
        element: dict[str, Any] = {
            "type": "chart",
            "description": f"[MOCK] Sample bar chart on page {page}.",
            "observations": ["[MOCK] Six bars, one per month."],
            "chart": {
                "chart_type": "bar",
                "x_axis": "Month",
                "y_axis": "Count",
                "key_values": ["Jan: 40", "Feb: 55", "Mar: 50"],
                "trend": "[MOCK] Values rise in the first quarter.",
            },
        }
    elif "scanned" in reasons:
        element = {
            "type": "scanned_text",
            "description": f"[MOCK] Scanned text on page {page}.",
            "transcription": "[MOCK] Sample transcription of a scanned page.",
        }
    else:
        element = {
            "type": "photo",
            "description": f"[MOCK] Sample photo on page {page}: a road scene in daylight.",
            "observations": [
                "[MOCK] One car is visible at the kerb.",
                "[MOCK] The road surface appears dry.",
            ],
            "possible_inferences": [
                {
                    "inference": "[MOCK] The photo was taken during the day.",
                    "basis": "[MOCK] Bright, even natural lighting.",
                }
            ],
            "information_gaps": ["[MOCK] The time the photo was taken is not shown."],
            "sensitive_content": {"graphic": False, "pii_visible": ["licence_plate"]},
        }
    return {"elements": [element]}


def _document_output(metadata: dict[str, Any]) -> dict[str, Any]:
    """Summary from the document's first sentences; one notable point per page (max 5)."""
    page_count = metadata.get("page_count", 1)
    sentences: dict[int, str] = {
        int(k): v for k, v in metadata.get("first_sentences", {}).items() if v
    }
    summary = " ".join(list(sentences.values())[:3]) or "The document has no text layer."
    points = [
        {"point": f"[MOCK] {text}", "page": page} for page, text in list(sentences.items())[:5]
    ] or [{"point": "[MOCK] The document has no extractable text.", "page": 1}]
    return {
        "document_type_guess": "[MOCK] document",
        "summary": f"[MOCK] {summary}",
        "main_topics": ["[MOCK] topic A", "[MOCK] topic B"],
        "key_entities": [
            {"name": "[MOCK] Sample location", "type": "location", "pages": [1]},
            {"name": "[MOCK] Sample organisation", "type": "organisation", "pages": [page_count]},
        ],
        "notable_points": points,
    }


def _chunk_notes_output(metadata: dict[str, Any]) -> dict[str, Any]:
    """One note per page of the chunk."""
    first, last = metadata.get("first_page", 1), metadata.get("last_page", 1)
    return {
        "notes": [
            {"page": page, "note": f"[MOCK] Note for page {page}."}
            for page in range(first, last + 1)
        ]
    }


def _consolidation_output(metadata: dict[str, Any]) -> dict[str, Any]:
    """Cross-document output citing page 1 of every document (labels D1, D2...)."""
    labels = list(metadata.get("documents", {"D1": 1}))
    every = [{"document": label, "page": 1} for label in labels]
    contradictions = (
        [
            {
                "topic": "[MOCK] Time of the incident",
                "positions": [
                    {"position": "[MOCK] About 21:15", "citation": every[0]},
                    {"position": "[MOCK] About 21:30", "citation": every[1]},
                ],
            }
        ]
        if len(labels) >= 2
        else []
    )
    return {
        "overall_summary": f"[MOCK] Consolidated summary of {len(labels)} documents.",
        "common_themes": [{"theme": "[MOCK] Shared theme", "citations": every}],
        "agreements": [
            {"point": "[MOCK] The documents agree on the location.", "citations": every}
        ],
        "contradictions": contradictions,
        "timeline": [
            {"time": "[MOCK] 21:15", "event": "[MOCK] Incident reported", "citations": every}
        ],
        "related_document_groups": [{"documents": labels, "reason": "[MOCK] Same incident."}],
        "information_gaps": ["[MOCK] No independent witness is cited."],
    }
