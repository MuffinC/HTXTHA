"""Triage review (confirm / override), feedback capture and stats over the API."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from tests import pdf_factory
from tests.conftest import app_client
from tests.test_incident_pipeline import _run_job
from tests.ticket_factory import TICKETS, WEAPON_TICKET, ticket_pdf


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with app_client(create_app(settings)) as client:
        yield client


async def _ticket_job(api: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, str]]:
    tickets = [*TICKETS, WEAPON_TICKET]
    job = await _run_job(api, [(f"{t.key}.pdf", ticket_pdf(t)) for t in tickets])
    ids = {d["filename"].removesuffix(".pdf"): d["document_id"] for d in job["documents"]}
    return job, ids


def _doc(job: dict[str, Any], document_id: str) -> dict[str, Any]:
    return next(d for d in job["documents"] if d["document_id"] == document_id)


async def test_mock_triage_matches_the_expected_table(api: httpx.AsyncClient) -> None:
    job, ids = await _ticket_job(api)
    priorities = {
        key: _doc(job, doc_id)["analysis"]["triage"]["suggested_priority"]
        for key, doc_id in ids.items()
    }
    assert priorities == {
        "t1_witness": "P3",
        "t2_taxi_driver": "P2",
        "t3_passenger": "P2",
        "t4_unrelated_tree": "P3",
        "t5_weapon_variant": "P1",
    }
    for doc in job["documents"]:
        triage = doc["analysis"]["triage"]
        assert triage["requires_human_review"] is True
        assert triage["analyst_override"] is None
        assert all(f["citation"]["page"] >= 1 for f in triage["triggering_factors"])

    groups = job["consolidated"]["related_document_groups"]
    same_incident = next(g for g in groups if len(g["document_ids"]) == 3)
    assert same_incident["priority"] == "P2"
    assert "does not lift" in same_incident["priority_reason"]


async def test_confirm_records_the_suggestion(api: httpx.AsyncClient) -> None:
    job, ids = await _ticket_job(api)
    doc_id = next(iter(ids.values()))
    suggested = _doc(job, doc_id)["analysis"]["triage"]["suggested_priority"]

    r = await api.put(
        f"/api/jobs/{job['job_id']}/documents/{doc_id}/triage", json={"action": "confirm"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["priority"] == suggested and r.json()["action"] == "confirm"

    job = (await api.get(f"/api/jobs/{job['job_id']}")).json()
    review = _doc(job, doc_id)["analysis"]["triage"]["analyst_override"]
    assert review["priority"] == suggested
    # The suggestion itself is unchanged: the analyst's decision sits alongside it.
    assert _doc(job, doc_id)["analysis"]["triage"]["suggested_priority"] == suggested


async def test_override_needs_a_reason_and_latest_wins(api: httpx.AsyncClient) -> None:
    job, ids = await _ticket_job(api)
    url = f"/api/jobs/{job['job_id']}/documents/{ids['t1_witness']}/triage"

    for body in (
        {"action": "override", "priority": "P1"},
        {"action": "override", "priority": "P1", "reason": "   ok  "},
        {"action": "override", "reason": "No priority given"},
    ):
        r = await api.put(url, json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    await api.put(
        url, json={"action": "override", "priority": "P4", "reason": "Duplicate of T2 report"}
    )
    r = await api.put(
        url, json={"action": "override", "priority": "P1", "reason": "Caller rang back"}
    )
    assert r.status_code == 200

    job = (await api.get(f"/api/jobs/{job['job_id']}")).json()
    review = _doc(job, ids["t1_witness"])["analysis"]["triage"]["analyst_override"]
    assert review["priority"] == "P1" and review["reason"] == "Caller rang back"


async def test_triage_review_404s(api: httpx.AsyncClient, settings: Settings) -> None:
    r = await api.put("/api/jobs/nope/documents/nope/triage", json={"action": "confirm"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    # General profile: there is no triage to review.
    job = await _run_job(api, [("doc.pdf", pdf_factory.valid_text_pdf())], profile="general")
    doc_id = job["documents"][0]["document_id"]
    r = await api.put(
        f"/api/jobs/{job['job_id']}/documents/{doc_id}/triage", json={"action": "confirm"}
    )
    assert r.status_code == 404
    assert "incident profile" in r.json()["error"]["message"]


async def test_feedback_and_stats(api: httpx.AsyncClient) -> None:
    empty = (await api.get("/api/feedback/stats")).json()
    assert empty["triage_agreement_rate"] is None and empty["total_up"] == 0

    job, ids = await _ticket_job(api)
    job_id = job["job_id"]
    for body in (
        {"target": "consolidated", "target_id": job_id, "rating": "up"},
        {"target": "section", "target_id": "summary", "rating": "down", "comment": "Too vague"},
        {"target": "section", "target_id": "summary", "rating": "up"},
    ):
        r = await api.post(f"/api/jobs/{job_id}/feedback", json=body)
        assert r.status_code == 201, r.text
        assert r.json()["id"] >= 1

    # Two kept (confirm, and an override to the same priority), one changed.
    t1, t2, t5 = ids["t1_witness"], ids["t2_taxi_driver"], ids["t5_weapon_variant"]
    base = f"/api/jobs/{job_id}/documents"
    await api.put(f"{base}/{t1}/triage", json={"action": "confirm"})
    await api.put(
        f"{base}/{t2}/triage",
        json={"action": "override", "priority": "P1", "reason": "Driver seriously hurt"},
    )
    await api.put(f"{base}/{t5}/triage", json={"action": "confirm"})

    stats = (await api.get("/api/feedback/stats")).json()
    assert stats["ratings"]["consolidated"] == {"up": 1, "down": 0}
    assert stats["ratings"]["section:summary"] == {"up": 1, "down": 1}
    assert (stats["total_up"], stats["total_down"]) == (2, 1)
    assert (stats["triage_reviewed"], stats["triage_kept"]) == (3, 2)
    assert stats["triage_agreement_rate"] == pytest.approx(0.667)


async def test_feedback_validation(api: httpx.AsyncClient) -> None:
    r = await api.post(
        "/api/jobs/nope/feedback", json={"target": "document", "target_id": "x", "rating": "up"}
    )
    assert r.status_code == 404
    job = await _run_job(api, [("doc.pdf", pdf_factory.valid_text_pdf())], profile="general")
    r = await api.post(
        f"/api/jobs/{job['job_id']}/feedback",
        json={"target": "document", "target_id": "x", "rating": "meh"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
