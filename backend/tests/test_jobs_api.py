"""End-to-end API tests: upload -> poll -> results, with the mock provider."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMTask
from app.main import DB_FILENAME, create_app
from app.schemas.jobs import DocumentStatus, ErrorInfo, JobStatus
from app.storage.repository import NewDocument, Repository
from app.storage.uploads import UploadStore
from tests import pdf_factory
from tests.conftest import app_client
from tests.llm_fakes import RecordingProvider

FINAL = {"completed", "partial", "failed"}


async def _upload(
    client: httpx.AsyncClient, files: list[tuple[str, bytes]], profile: str = "general"
) -> httpx.Response:
    return await client.post(
        "/api/jobs",
        files=[("files", (name, data, "application/pdf")) for name, data in files],
        data={"profile": profile},
    )


async def _wait(client: httpx.AsyncClient, job_id: str, timeout: float = 30) -> dict[str, Any]:
    """Poll like the frontend does, until the job reaches a final status."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        body = (await client.get(f"/api/jobs/{job_id}")).json()
        if body["status"] in FINAL:
            return body
        assert asyncio.get_running_loop().time() < deadline, f"job stuck: {body['status']}"
        await asyncio.sleep(0.05)


# --------------------------------------------------------------------------- happy path


async def test_upload_poll_results_end_to_end(client: httpx.AsyncClient) -> None:
    response = await _upload(
        client,
        [
            ("report.pdf", pdf_factory.valid_text_pdf(2)),
            ("chart.pdf", pdf_factory.vector_chart_pdf()),
        ],
    )
    assert response.status_code == 202
    created = response.json()
    assert [a["filename"] for a in created["accepted"]] == ["report.pdf", "chart.pdf"]
    assert created["rejected"] == []

    job = await _wait(client, created["job_id"])

    assert job["status"] == "completed"
    ids = {d["document_id"] for d in job["documents"]}
    assert ids == {a["document_id"] for a in created["accepted"]}
    for doc in job["documents"]:
        assert doc["status"] == "completed"
        assert doc["analysis"]["summary"].startswith("[MOCK]")
    chart = job["documents"][1]["analysis"]
    assert chart["visual_elements"][0]["type"] == "chart"
    assert chart["visual_elements"][0]["ai_generated"] is True

    report = job["consolidated"]
    assert report["overall_summary"].startswith("[MOCK]")
    cited = {c["document_id"] for t in report["common_themes"] for c in t["citations"]}
    assert cited == ids  # D1/D2 labels were mapped back to real IDs
    assert report["contradictions"][0]["positions"][0]["citation"]["document_id"] in ids
    assert job["consolidated_error"] is None


async def test_profiles_lists_general_and_incident_as_available(client: httpx.AsyncClient) -> None:
    profiles = (await client.get("/api/profiles")).json()
    assert {p["id"]: p["available"] for p in profiles} == {
        "general": True,
        "incident": True,
        "statistical": False,
    }
    assert all(p["description"] for p in profiles)


# --------------------------------------------------------------------------- validation


async def test_mixed_upload_accepts_valid_and_reports_rejected(client: httpx.AsyncClient) -> None:
    response = await _upload(
        client,
        [
            ("good.pdf", pdf_factory.valid_text_pdf()),
            ("fake.pdf", pdf_factory.fake_pdf()),
            ("locked.pdf", pdf_factory.encrypted_pdf()),
        ],
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body["accepted"]) == 1
    assert [(r["filename"], r["code"]) for r in body["rejected"]] == [
        ("fake.pdf", "UNSUPPORTED_TYPE"),
        ("locked.pdf", "ENCRYPTED_PDF"),
    ]

    job = await _wait(client, body["job_id"])
    assert job["status"] == "completed"  # rejected files do not make a job partial
    assert [d["status"] for d in job["documents"]] == ["completed", "rejected", "rejected"]
    assert job["documents"][1]["error"]["code"] == "UNSUPPORTED_TYPE"
    assert job["consolidated"] is None
    assert job["consolidated_error"]["code"] == "SINGLE_DOCUMENT"


async def test_all_files_rejected_returns_400(client: httpx.AsyncClient) -> None:
    response = await _upload(
        client, [("a.pdf", pdf_factory.fake_pdf()), ("b.pdf", pdf_factory.empty_pdf())]
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "NO_VALID_FILES"
    assert [r["code"] for r in error["details"]["rejected"]] == [
        "UNSUPPORTED_TYPE",
        "EMPTY_DOCUMENT",
    ]


async def test_too_many_files_returns_400(make_settings: Any) -> None:
    async with app_client(create_app(make_settings(max_files=2))) as client:
        pdf = pdf_factory.valid_text_pdf()
        response = await _upload(client, [("a.pdf", pdf), ("b.pdf", pdf), ("c.pdf", pdf)])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TOO_MANY_FILES"


async def test_oversized_file_is_rejected_while_streaming(make_settings: Any) -> None:
    big = pdf_factory.valid_text_pdf() + b"0" * (1024 * 1024)  # just over 1 MB
    async with app_client(create_app(make_settings(max_file_mb=1, max_files=3))) as client:
        response = await _upload(
            client, [("big.pdf", big), ("ok.pdf", pdf_factory.valid_text_pdf())]
        )
    assert response.status_code == 202
    assert response.json()["rejected"][0]["code"] == "FILE_TOO_LARGE"


async def test_request_over_total_limit_is_refused_before_parsing(make_settings: Any) -> None:
    big = b"%PDF-" + b"0" * (3 * 1024 * 1024)  # limit is 1 file x 1 MB + 1 MB overhead
    async with app_client(create_app(make_settings(max_file_mb=1, max_files=1))) as client:
        response = await _upload(client, [("big.pdf", big)])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_unavailable_profile_returns_400(client: httpx.AsyncClient) -> None:
    response = await _upload(
        client, [("a.pdf", pdf_factory.valid_text_pdf())], profile="statistical"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_PROFILE"


async def test_unknown_profile_and_missing_files_return_422(client: httpx.AsyncClient) -> None:
    bad_profile = await _upload(client, [("a.pdf", pdf_factory.valid_text_pdf())], profile="x")
    no_files = await client.post("/api/jobs", data={"profile": "general"})
    assert bad_profile.status_code == 422 and no_files.status_code == 422
    assert no_files.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_job_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- failures


async def test_one_failed_document_makes_job_partial(settings: Settings) -> None:
    valid = json.dumps(
        {
            "document_type_guess": "report",
            "summary": "Fine.",
            "main_topics": [],
            "key_entities": [],
            "notable_points": [],
        }
    )
    # Document 1 succeeds; document 2 is invalid twice (first attempt + one retry).
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [valid, "{}", "{}"]})
    async with app_client(create_app(settings, provider=provider)) as client:
        created = (
            await _upload(
                client,
                [("a.pdf", pdf_factory.valid_text_pdf()), ("b.pdf", pdf_factory.valid_text_pdf())],
            )
        ).json()
        job = await _wait(client, created["job_id"])

    assert job["status"] == "partial"
    assert [d["status"] for d in job["documents"]] == ["completed", "failed"]
    assert job["documents"][1]["error"]["code"] == "LLM_OUTPUT_INVALID"
    assert job["documents"][1]["analysis"] is None
    assert job["consolidated_error"]["code"] == "SINGLE_DOCUMENT"


async def test_consolidation_failure_keeps_documents_and_marks_partial(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.CONSOLIDATION: ["{}", "{}"]})
    async with app_client(create_app(settings, provider=provider)) as client:
        pdf = pdf_factory.valid_text_pdf()
        created = (await _upload(client, [("a.pdf", pdf), ("b.pdf", pdf)])).json()
        job = await _wait(client, created["job_id"])

    assert job["status"] == "partial"
    assert [d["status"] for d in job["documents"]] == ["completed", "completed"]
    assert job["consolidated"] is None
    assert job["consolidated_error"]["code"] == "LLM_OUTPUT_INVALID"


async def test_every_document_failing_fails_the_job(settings: Settings) -> None:
    provider = RecordingProvider({LLMTask.DOCUMENT_ANALYSIS: [RuntimeError("boom")]})
    async with app_client(create_app(settings, provider=provider)) as client:
        created = (await _upload(client, [("a.pdf", pdf_factory.valid_text_pdf())])).json()
        job = await _wait(client, created["job_id"])

    assert job["status"] == "failed"
    assert job["error"]["code"] == "NO_DOCUMENT_ANALYSED"
    assert job["documents"][0]["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
    }


# --------------------------------------------------------------------------- lifecycle


async def test_interrupted_jobs_are_failed_on_startup(settings: Settings, tmp_path: Path) -> None:
    # Simulate a previous run that died mid-job.
    repo = Repository(tmp_path / DB_FILENAME)
    job_id, doc_id = "22222222-0000-4000-8000-000000000000", "cccccccc-0000-4000-8000-000000000003"
    repo.create_job(job_id, "general", [NewDocument(doc_id, "a.pdf", 10, 1, DocumentStatus.QUEUED)])
    repo.set_job_status(job_id, JobStatus.PROCESSING)
    repo.set_document_status(doc_id, DocumentStatus.ANALYSING)
    repo.close()
    UploadStore(tmp_path).save(doc_id, b"%PDF-1.7 leftover")

    async with app_client(create_app(settings)) as client:
        job = (await client.get(f"/api/jobs/{job_id}")).json()

    assert job["status"] == "failed"
    assert job["error"]["code"] == "INTERRUPTED"
    assert "restarted" in job["error"]["message"]
    assert job["documents"][0]["status"] == "failed"
    assert not UploadStore(tmp_path).path(doc_id).exists()


async def test_uploads_deleted_after_processing(client: httpx.AsyncClient, tmp_path: Path) -> None:
    created = (await _upload(client, [("a.pdf", pdf_factory.valid_text_pdf())])).json()
    await _wait(client, created["job_id"])
    assert list((tmp_path / "uploads").iterdir()) == []


async def test_uploads_kept_when_retain_uploads(make_settings: Any, tmp_path: Path) -> None:
    async with app_client(create_app(make_settings(retain_uploads=True))) as client:
        created = (await _upload(client, [("a.pdf", pdf_factory.valid_text_pdf())])).json()
        await _wait(client, created["job_id"])
    [stored] = list((tmp_path / "uploads").iterdir())
    assert stored.name == f"{created['accepted'][0]['document_id']}.pdf"  # UUID, not "a.pdf"


async def test_wrapped_pdf_is_stored_from_its_header(make_settings: Any, tmp_path: Path) -> None:
    # D-074: the bytes before %PDF- are never stored, and the job completes with a warning.
    inner = pdf_factory.valid_text_pdf()
    async with app_client(create_app(make_settings(retain_uploads=True))) as client:
        created = (
            await _upload(client, [("w.pdf", pdf_factory.multipart_wrapped_pdf(inner))])
        ).json()
        job = await _wait(client, created["job_id"])
    [accepted] = created["accepted"]
    assert [w["code"] for w in accepted["warnings"]] == ["LEADING_BYTES_IGNORED"]
    [stored] = list((tmp_path / "uploads").iterdir())
    assert stored.read_bytes().startswith(b"%PDF-")
    assert stored.read_bytes()[: len(inner)] == inner
    assert job["status"] == "completed"
    warnings = job["documents"][0]["analysis"]["warnings"]
    assert "LEADING_BYTES_IGNORED" in [w["code"] for w in warnings]


async def test_logs_carry_ids_and_no_document_content(
    make_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    # Built inside the test (after capsys is active) at INFO, so stage logs are captured.
    async with app_client(create_app(make_settings(log_level="INFO"))) as client:
        pdf = pdf_factory.valid_text_pdf()
        created = (await _upload(client, [("secret-name.pdf", pdf)])).json()
        await _wait(client, created["job_id"])

    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    stage_lines = [line for line in lines if line.get("stage") == "analysing"]
    assert stage_lines, "expected stage logs"
    doc_id = created["accepted"][0]["document_id"]
    assert all(line["job_id"] == created["job_id"] for line in stage_lines)
    assert all(line["document_id"] == doc_id for line in stage_lines)
    text = "\n".join(json.dumps(line) for line in lines)
    assert "community centre" not in text  # document text
    assert "secret-name" not in text  # filename


def test_repository_error_info_round_trip(tmp_path: Path) -> None:
    """Guard: ErrorInfo codes that are not ErrorCode members (e.g. SINGLE_DOCUMENT) persist."""
    repo = Repository(tmp_path / "x.sqlite3")
    repo.create_job("j", "general", [])
    repo.save_consolidated("j", None, ErrorInfo(code="SINGLE_DOCUMENT", message="m"))
    job = repo.get_job("j")
    assert job is not None and job.consolidated_error == ErrorInfo(
        code="SINGLE_DOCUMENT", message="m"
    )


async def test_config_exposes_upload_limits_from_settings(make_settings: Any) -> None:
    async with app_client(create_app(make_settings(max_files=3, max_file_mb=7))) as client:
        body = (await client.get("/api/config")).json()
    assert body["max_files"] == 3 and body["max_file_mb"] == 7
    assert set(body) == {
        "max_files",
        "max_file_mb",
        "max_pages",
        "max_visual_pages_per_doc",
        "active_content_policy",
        "embedded_file_policy",
        "mask_pii",
        "retain_uploads",
    }  # nothing sensitive (URLs, paths, model internals) leaks


async def test_mock_delay_slows_calls_and_mock_fail_fails_analysis() -> None:
    import time

    from app.llm.base import LLMRequest
    from app.llm.mock import MockProvider

    request = LLMRequest(
        task=LLMTask.DOCUMENT_ANALYSIS,
        system="",
        prompt="",
        json_schema={},
        metadata={"first_sentences": {1: "MOCK_FAIL: break this one."}},
    )
    started = time.perf_counter()
    result = await MockProvider(delay_seconds=0.05).complete(request)
    # Tolerance: Windows timers can wake a few ms early.
    assert time.perf_counter() - started >= 0.04
    assert result.text == "{}"  # invalid for the schema: drives the real failure path
