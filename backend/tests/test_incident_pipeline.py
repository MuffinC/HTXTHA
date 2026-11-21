"""Incident profile end to end (mock provider) and its failure paths."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMTask
from app.main import create_app
from app.pipeline.analysis import analyse_document
from app.pipeline.extraction import extract_document
from app.pipeline.visual import analyse_visuals
from app.schemas.common import WarningCode
from tests import pdf_factory
from tests.conftest import app_client
from tests.llm_fakes import RecordingProvider
from tests.ticket_factory import PLANTED, T4, TICKETS, ticket_pdf


async def _run_job(
    client: httpx.AsyncClient, files: list[tuple[str, bytes]], profile: str = "incident"
) -> dict[str, Any]:
    response = await client.post(
        "/api/jobs",
        files=[("files", (n, d, "application/pdf")) for n, d in files],
        data={"profile": profile},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    for _ in range(400):
        job: dict[str, Any] = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in {"completed", "partial", "failed"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture
async def ticket_job(settings: Settings) -> dict[str, Any]:
    async with app_client(create_app(settings)) as client:
        return await _run_job(client, [(f"{t.key}.pdf", ticket_pdf(t)) for t in TICKETS])


async def test_tickets_are_grouped_and_compared_by_rule(ticket_job: dict[str, Any]) -> None:
    job = ticket_job
    assert job["status"] == "completed"
    key_by_id = {d["document_id"]: d["filename"].removesuffix(".pdf") for d in job["documents"]}
    report = job["consolidated"]

    assert report["rule_based"] is True
    [group] = report["related_document_groups"]
    assert {key_by_id[i] for i in group["document_ids"]} == PLANTED["same_incident"]
    assert group["reason"].startswith("Same incident by rule")
    assert report["possibly_related_groups"] == []

    topics = {c["topic"]: c for c in report["contradictions"]}
    assert set(topics) == PLANTED["contradictions"]
    # Absence is never a contradiction: T3 does not mention the light.
    light_ids = {p["citation"]["document_id"] for p in topics["Traffic light"]["positions"]}
    assert "t3_passenger" not in {key_by_id[i] for i in light_ids}
    assert len(report["timeline"]) == 4


async def test_narrative_vs_photo_checks_and_claim_corroboration(
    ticket_job: dict[str, Any],
) -> None:
    t4 = next(d for d in ticket_job["documents"] if d["filename"] == f"{T4.key}.pdf")
    incident = t4["analysis"]["incident"]

    results = {c["check"].split(":")[0]: c["result"] for c in incident["consistency_checks"]}
    assert {k for k, v in results.items() if v == "inconsistent"} == PLANTED["inconsistent_checks"][
        "t4_unrelated_tree"
    ]
    weather_claim = next(c for c in incident["claims"] if c["claim"].startswith("Weather"))
    assert weather_claim["corroboration"] == "contradicted"
    assert incident["derived"]["incident_time"]["value"] == "23:00"
    assert incident["derived"]["expected_lighting"]["value"] == "night"
    # The photo element carries the structured scene in the incident profile.
    [photo] = t4["analysis"]["visual_elements"]
    assert photo["scene"]["lighting"] == "daylight"


async def test_ticket_without_photo_says_so(ticket_job: dict[str, Any]) -> None:
    t2 = next(d for d in ticket_job["documents"] if d["filename"] == "t2_taxi_driver.pdf")
    incident = t2["analysis"]["incident"]
    assert incident["consistency_checks"] == []
    assert all(c["note"] == "No photo attached." for c in incident["claims"])
    assert incident["derived"]["incident_date"]["value"] == "2025-03-14"  # from "last night"
    assert any("No photo attached" in g for g in incident["missing_information"])


async def test_general_profile_has_no_incident_extension(settings: Settings) -> None:
    async with app_client(create_app(settings)) as client:
        job = await _run_job(
            client, [(f"{t.key}.pdf", ticket_pdf(t)) for t in TICKETS[:2]], profile="general"
        )
    assert all(d["analysis"]["incident"] is None for d in job["documents"])
    assert job["consolidated"]["rule_based"] is False


# --------------------------------------------------------------------------- failure paths


async def _analyse_incident(provider: RecordingProvider, settings: Settings) -> Any:
    data = ticket_pdf(TICKETS[0])
    extracted = extract_document(data, settings)
    return await analyse_document(
        document_id="d1",
        filename="t1.pdf",
        extracted=extracted,
        visual_elements=[],
        warnings=[],
        profile="incident",
        provider=provider,
        settings=settings,
    )


async def test_failed_extraction_keeps_core_analysis_with_warning(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.INCIDENT_EXTRACTION: ["{}", "{}"]})
    analysis = await _analyse_incident(provider, settings)

    assert analysis.incident is None
    assert analysis.summary  # the general analysis is still there
    assert [w.code for w in analysis.warnings] == [WarningCode.INCIDENT_EXTRACTION_FAILED]
    assert len(provider.calls(LLMTask.INCIDENT_EXTRACTION)) == 2  # one retry


async def test_fact_pages_that_do_not_exist_are_removed(settings: Settings) -> None:
    mock_output = json.loads(
        (await RecordingProvider().complete((await _first_extraction_request(settings)))).text
    )
    mock_output["facts"]["traffic_light"]["page"] = 9  # the ticket has 2 pages
    mock_output["other_claims"] = [{"claim": "Invented", "page": 7}]
    provider = RecordingProvider({LLMTask.INCIDENT_EXTRACTION: [json.dumps(mock_output)]})

    analysis = await _analyse_incident(provider, settings)

    assert analysis.incident.facts.traffic_light.page is None
    assert not any(c.claim == "Invented" for c in analysis.incident.claims)
    assert any(w.code is WarningCode.CITATIONS_REMOVED for w in analysis.warnings)


async def _first_extraction_request(settings: Settings) -> Any:
    """The request the pipeline sends for extraction (to get realistic mock output)."""
    provider = RecordingProvider()
    await _analyse_incident(provider, settings)
    return provider.calls(LLMTask.INCIDENT_EXTRACTION)[0]


async def test_incident_people_are_recorded_by_role(settings: Settings) -> None:
    provider = RecordingProvider()
    await _analyse_incident(provider, settings)
    prompt = provider.calls(LLMTask.DOCUMENT_ANALYSIS)[0].prompt
    assert "record people by ROLE only" in prompt
    assert "by ROLE only" in provider.calls(LLMTask.INCIDENT_EXTRACTION)[0].prompt


async def test_scene_is_kept_only_on_photos(settings: Settings) -> None:
    scene = {
        "lighting": "night_street_lit",
        "weather": "clear",
        "road_surface": "dry",
        "vehicles_visible": "2",
        "vehicle_types": ["car"],
        "damage_locations": ["front"],
        "traffic_signal": "green",
        "timestamp_visible": None,
    }
    output = json.dumps(
        {
            "elements": [
                {"type": "photo", "description": "Two cars.", "scene": scene},
                {"type": "chart", "description": "A chart.", "scene": scene},
            ]
        }
    )
    data = pdf_factory.photo_pdf()
    result = await analyse_visuals(
        data,
        extract_document(data, settings),
        "incident",
        RecordingProvider({LLMTask.VISUAL_ANALYSIS: [output]}),
        settings,
    )
    photo, chart = result.elements
    assert photo.scene is not None and photo.scene.traffic_signal == "green"
    assert chart.scene is None


async def test_incident_visual_schema_requires_scene(settings: Settings) -> None:
    # Without "scene" the incident visual output is invalid: the model must answer it.
    output = json.dumps({"elements": [{"type": "photo", "description": "A car."}]})
    data = pdf_factory.photo_pdf()
    result = await analyse_visuals(
        data,
        extract_document(data, settings),
        "incident",
        RecordingProvider({LLMTask.VISUAL_ANALYSIS: [output]}),
        settings,
    )
    assert result.elements == []
    assert result.warnings[0].code is WarningCode.VISUAL_ANALYSIS_FAILED


async def test_consolidation_prompt_carries_rule_findings_without_quotes(
    settings: Settings,
) -> None:
    provider = RecordingProvider()
    async with app_client(create_app(settings, provider=provider)) as client:
        await _run_job(client, [(f"{t.key}.pdf", ticket_pdf(t)) for t in TICKETS])

    [request] = provider.calls(LLMTask.CONSOLIDATION)
    findings = request.prompt.split("RULE-BASED FINDINGS")[1].split("Write only")[0]
    assert "Same incident: D1, D2, D3." in findings
    assert "Contradiction on Traffic light: D1: green; D2: red." in findings
    assert "“" not in findings  # no quoted document text outside the untrusted markers
    assert set(request.json_schema["properties"]) == {
        "overall_summary",
        "common_themes",
        "information_gaps",
    }
