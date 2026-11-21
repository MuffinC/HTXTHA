"""Live end-to-end test: two documents through the real API and the real model.

Opt-in: ``pytest -m ollama``. Uploads two synthetic reports of the same
incident, with deliberate contradictions (time 21:15 vs 21:30, light green vs
red, two vehicles vs three). Report A has an attached photo, so all four stages
run. Asserts the pipeline contract (statuses, citations resolve to real
documents and pages) and records the total job time and what the model found.
"""

import asyncio
import time
from typing import Any

import pytest

from app.config import Settings
from app.llm.ollama import OllamaProvider
from app.main import create_app
from tests import pdf_factory
from tests.conftest import app_client
from tests.integration.conftest import NOTES, TIMINGS

pytestmark = pytest.mark.ollama

JOB_TIMEOUT_SECONDS = 600


async def test_two_documents_end_to_end(
    live_provider: OllamaProvider, live_settings: Settings
) -> None:
    app = create_app(live_settings, provider=live_provider)
    async with app_client(app) as client:
        started = time.perf_counter()
        response = await client.post(
            "/api/jobs",
            files=[
                ("files", ("report_a.pdf", pdf_factory.incident_report_pdf(), "application/pdf")),
                ("files", ("report_b.pdf", pdf_factory.witness_report_pdf(), "application/pdf")),
            ],
            data={"profile": "general"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        job: dict[str, Any] = {}
        while time.perf_counter() - started < JOB_TIMEOUT_SECONDS:
            job = (await client.get(f"/api/jobs/{job_id}")).json()
            if job["status"] in {"completed", "partial", "failed"}:
                break
            await asyncio.sleep(1)
        total = time.perf_counter() - started

    TIMINGS.append(("end-to-end job: 2 docs (3 pages, 1 photo)", total))
    assert job["status"] == "completed", job

    pages = {d["document_id"]: d["page_count"] for d in job["documents"]}
    for doc in job["documents"]:
        analysis = doc["analysis"]
        assert analysis["summary"]
        for point in analysis["notable_points"]:
            assert 1 <= point["page"] <= doc["page_count"]
    assert job["documents"][0]["analysis"]["visual_elements"], "report A's photo was not analysed"

    report = job["consolidated"]
    assert report["overall_summary"]
    citations = [c for t in report["common_themes"] for c in t["citations"]]
    citations += [p["citation"] for c in report["contradictions"] for p in c["positions"]]
    for citation in citations:
        assert citation["document_id"] in pages
        assert 1 <= citation["page"] <= pages[citation["document_id"]]

    removed = [
        w
        for d in job["documents"]
        for w in d["analysis"]["warnings"]
        if w["code"] == "CITATIONS_REMOVED"
    ] + [w for w in report["warnings"] if w["code"] == "CITATIONS_REMOVED"]
    NOTES.append(f"e2e contradictions found: {[c['topic'] for c in report['contradictions']]}")
    NOTES.append(f"e2e related groups: {len(report['related_document_groups'])}")
    NOTES.append(f"e2e CITATIONS_REMOVED warnings: {len(removed)}")
