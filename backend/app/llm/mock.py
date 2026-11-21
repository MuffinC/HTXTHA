"""Mock provider: deterministic, schema-valid output with no model.

Lets the whole app run, demo and be tested on a machine without Ollama or a GPU
(CLAUDE.md principle 6). Output is derived from the request metadata (page
numbers, why a page needed visual analysis, the first sentence of each page,
the document labels), so the UI looks realistic, and it is
returned as JSON *text*, so it goes through the same parsing and validation as
real model output.

Every mock text starts with "[MOCK]" so it can never be mistaken for real analysis.

Two demo aids, so every UI state can be shown without a model:

* ``MOCK_DELAY_SECONDS`` pauses each call, so progress is visible.
* A document with ``MOCK_FAIL`` in the first sentence of any page gets invalid output for its
  analysis (twice, so the one retry fails too), which drives the real
  ``LLM_OUTPUT_INVALID`` failure path and lets a job end ``partial`` or ``failed``.
"""

import asyncio
import json
import re
from typing import Any

from app.llm.base import LLMProvider, LLMRequest, LLMResult, LLMTask

#: Text that makes the mock fail a document's analysis (demo/test aid, mock only).
MOCK_FAIL = "MOCK_FAIL"


class MockProvider(LLMProvider):
    """Returns canned output keyed on ``request.task``."""

    name = "mock"
    model = "mock"

    def __init__(self, delay_seconds: float = 0) -> None:
        self._delay = delay_seconds

    async def complete(self, request: LLMRequest) -> LLMResult:
        """Return deterministic JSON for the request's task."""
        if self._delay:
            await asyncio.sleep(self._delay)
        if request.task is LLMTask.DOCUMENT_ANALYSIS and _wants_failure(request.metadata):
            return LLMResult(text="{}", model=self.model, duration_ms=0, done_reason="stop")
        builders = {
            LLMTask.VISUAL_ANALYSIS: _visual_output,
            LLMTask.DOCUMENT_ANALYSIS: _document_output,
            LLMTask.CHUNK_NOTES: _chunk_notes_output,
            LLMTask.CONSOLIDATION: _consolidation_output,
            LLMTask.INCIDENT_EXTRACTION: _incident_output,
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


def _wants_failure(metadata: dict[str, Any]) -> bool:
    """True if the first sentence of any page contains the MOCK_FAIL trigger."""
    return any(MOCK_FAIL in text for text in metadata.get("first_sentences", {}).values())


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
            # Used by the incident profile (required there; ignored by the general schema).
            "scene": {
                "lighting": "daylight",
                "weather": "clear",
                "road_surface": "dry",
                "vehicles_visible": "1",
                "vehicle_types": ["car"],
                "damage_locations": ["front"],
                "traffic_signal": "not_visible",
                "timestamp_visible": None,
            },
        }
    element.setdefault("scene", _UNCLEAR_SCENE)
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


_UNCLEAR_SCENE: dict[str, Any] = {
    "lighting": "unclear",
    "weather": "unclear",
    "road_surface": "unclear",
    "vehicles_visible": "unclear",
    "vehicle_types": [],
    "damage_locations": [],
    "traffic_signal": "unclear",
    "timestamp_visible": None,
}

# ---------------------------------------------------------------- incident extraction
# Keyword matching over the page text, so the incident UI (grouping, contradictions,
# consistency checks) behaves realistically on the sample tickets without a model.
# It is deliberately simple; the real extraction is done by the model.

_FORM_FIELDS = {
    "reference_no": r"(?:reference(?: no\.?)?|ref)[:\s]+([A-Z]{2,6}(?:-\d{2,6})+)",
    "submitted_at": r"submitted(?: on)?[:\s]+([^\n]+)",
    "occurred_date": r"date of incident[:\s]+([^\n]+)",
    "occurred_time": r"(?:approx\.? )?time of incident[:\s]+([^\n]+)",
    "location": r"location(?: of incident)?[:\s]+([^\n]+)",
}
_NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4_or_more"}


# Form labels of the e-report layout; any other "Words: more words" line is prose.
_FORM_LINE = re.compile(
    r"^(?:reference no|submitted on|category|date of incident|approx\. time of incident|"
    r"location|reporter|contact number|attachments|declaration)\b[^:]*:",
    re.IGNORECASE,
)


def _sentences(page_texts: dict[Any, str]) -> list[tuple[int, str]]:
    """Narrative sentences per page. "Label: value" form lines are skipped, and the
    remaining lines are re-joined first, because PDF text wraps mid-sentence."""
    out: list[tuple[int, str]] = []
    for page, text in page_texts.items():
        prose = " ".join(line for line in text.splitlines() if not _FORM_LINE.match(line.strip()))
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(prose.split())):
            if len(sentence) >= 20:
                out.append((int(page), sentence))
    return out


def _find(
    sentences: list[tuple[int, str]], pattern: str, value: str | None = None
) -> dict[str, Any] | None:
    for page, sentence in sentences:
        match = re.search(pattern, sentence, re.IGNORECASE)
        if match:
            # First group that matched (patterns may have alternatives).
            found = value or next(g for g in match.groups() if g).lower()
            return {"value": found, "as_written": sentence[:160], "page": page}
    return None


def _incident_output(metadata: dict[str, Any]) -> dict[str, Any]:
    page_texts: dict[Any, str] = metadata.get("page_texts", {})
    full = "\n".join(page_texts.values())
    sentences = _sentences(page_texts)
    narrative = sentences

    def form(name: str) -> str | None:
        m = re.search(_FORM_FIELDS[name], full, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def first(*options: dict[str, Any] | None) -> dict[str, Any]:
        return next((o for o in options if o), {"value": "not_mentioned"})

    count = _find(
        narrative, r"\b(one|two|three|four)\s+(?:cars?|vehicles?)\b(?! (?:was|were) waiting)"
    )
    if count:
        count["value"] = _NUMBERS.get(count["value"], "not_mentioned")
    facts = {
        "traffic_light": first(
            _find(narrative, r"\b(red|amber|green)\b.*\blight|\blight\b.*\b(red|amber|green)\b")
        ),
        "vehicle_count": first(count),
        "weather": first(
            _find(narrative, r"\b(rain(?:ing)?|drizzle|downpour)\b", "rain"),
            _find(narrative, r"\bweather was (?:dry|fine|clear)\b", "clear"),
        ),
        "road_surface": first(
            _find(narrative, r"\broad was (wet|dry|flooded)\b"),
            _find(narrative, r"\b(wet|flooded) road\b"),
        ),
        "lighting": first(
            _find(narrative, r"\bstreet ?lights? (?:were|was) on\b", "night_street_lit"),
            _find(narrative, r"\b(?:very|pitch) dark\b", "night_dark"),
        ),
        "injuries": first(
            _find(
                narrative,
                r"\b(?:nobody|no one) (?:was|appeared to be) (?:hurt|injured)|no injuries\b"
                r"|\b(?:was|were) not (?:hurt|injured)\b",
                "none",
            ),
            _find(narrative, r"\b(?:hurt|injur\w*|holding (?:his|her) arm|bleeding)\b", "injury"),
        ),
        "party_left_scene": first(
            _find(narrative, r"\b(?:drove|rode|sped) off\b|\bleft the scene\b", "yes"),
            _find(narrative, r"\b(?:both|all) (?:drivers|parties) stayed\b", "no"),
        ),
        "vehicle_types": sorted(
            {
                t
                for t in ("car", "taxi", "motorcycle", "bus", "lorry", "van")
                if re.search(rf"\b{t}s?\b", full, re.I)
            }
        ),
        "damage_locations": [],
    }
    for name, fact in facts.items():
        if isinstance(fact, dict) and fact["value"] == "not_mentioned":
            facts[name] = {"value": "not_mentioned", "as_written": None, "page": None}
    collision = re.search(r"\b(collid\w*|collision|crash\w*|hit)\b", full, re.I)
    return {
        "reference_no": form("reference_no"),
        "submitted_at": form("submitted_at"),
        "occurred_date": form("occurred_date"),
        "occurred_time": form("occurred_time"),
        "location": form("location"),
        "category": "road_traffic" if collision else "other",
        "category_confidence": "medium",
        "narrative_summary": "[MOCK] " + (narrative[0][1] if narrative else "No narrative found."),
        "parties": [
            {"role": "[MOCK] reporter", "description": "[MOCK] the person who submitted the report"}
        ],
        "facts": facts,
        "other_claims": [],
        "missing_information": [],
    }
