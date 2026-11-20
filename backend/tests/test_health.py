"""Tests for GET /api/health and the Ollama readiness check."""

from pathlib import Path

import httpx
import pytest

from app.api.health import ollama_model_ready
from app.config import Settings
from app.main import create_app


async def test_health_mock_provider_is_ready(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "mock",
        "model": "mock",
        "model_ready": True,
    }


async def test_health_ollama_unreachable_reports_degraded(tmp_path: Path) -> None:
    # Nothing listens on port 9 locally; the check must fail fast and report
    # "degraded" with HTTP 200 instead of raising.
    settings = Settings(
        llm_provider="ollama",
        ollama_base_url="http://127.0.0.1:9",
        data_dir=tmp_path,
        log_level="WARNING",
    )
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["provider"] == "ollama"
    assert body["model_ready"] is False


def _tags_transport(model_names: list[str], status: int = 200) -> httpx.MockTransport:
    """Fake Ollama ``/api/tags`` endpoint listing the given models."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(status, json={"models": [{"name": n} for n in model_names]})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("requested", "available", "expected"),
    [
        ("qwen3-vl:4b-instruct", ["qwen3-vl:4b-instruct"], True),
        ("qwen3-vl:4b-instruct", ["qwen3-vl:8b-instruct"], False),
        ("llava", ["llava:latest"], True),  # an untagged request means :latest
        ("qwen3-vl:4b-instruct", [], False),  # model not pulled yet
    ],
)
async def test_ollama_model_ready_matches_tags(
    requested: str, available: list[str], expected: bool
) -> None:
    ready = await ollama_model_ready(
        "http://ollama", requested, transport=_tags_transport(available)
    )
    assert ready is expected


async def test_ollama_model_ready_handles_server_error() -> None:
    ready = await ollama_model_ready(
        "http://ollama", "any", transport=_tags_transport([], status=500)
    )
    assert ready is False


async def test_openapi_docs_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
