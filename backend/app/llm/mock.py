"""Mock provider: deterministic, schema-valid output with no model.

Lets the whole app run, demo and be tested on a machine without Ollama or a GPU
(CLAUDE.md principle 6). Output is derived from the request (page number and
why the page needed visual analysis), so the UI looks realistic, and it is
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
        if request.task is LLMTask.VISUAL_ANALYSIS:
            payload = _visual_output(request.metadata)
        else:  # pragma: no cover - new tasks must add a branch here
            raise NotImplementedError(f"MockProvider has no output for task {request.task}")
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
