"""Health endpoint: reports whether the backend and its model are ready.

The frontend polls this to show a "model downloading / not ready" banner, so it
always returns HTTP 200 with a status body rather than failing when Ollama is
down. ``status`` is ``"ok"`` when the model is usable, otherwise ``"degraded"``.

NOTE: in M2 the Ollama check moves behind the LLM provider interface
(``app/llm``). It lives here for M0 so the endpoint works from day one.
"""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Short timeout: health is polled frequently and must stay responsive.
HEALTH_CHECK_TIMEOUT_SECONDS = 3.0


class HealthResponse(BaseModel):
    """Response body for ``GET /api/health``."""

    status: Literal["ok", "degraded"]
    provider: Literal["ollama", "mock"]
    model: str
    model_ready: bool


def _model_matches(requested: str, available: str) -> bool:
    """Return True if an Ollama model name satisfies the requested tag.

    Ollama lists models with an explicit tag (``name:tag``). A request without
    a tag means ``:latest``.
    """
    if ":" not in requested:
        requested = f"{requested}:latest"
    return requested == available


async def ollama_model_ready(
    base_url: str,
    model: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Check that Ollama is reachable and ``model`` has been pulled.

    Args:
        base_url: Ollama server URL, e.g. ``http://ollama:11434``.
        model: Model tag to look for.
        transport: Optional httpx transport, injected by tests.

    Returns:
        True if the model is listed by ``GET /api/tags``; False if Ollama is
        unreachable, returns an error, or the model is not pulled yet.
    """
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=HEALTH_CHECK_TIMEOUT_SECONDS, transport=transport
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError) as exc:
        # Expected during first start-up while Ollama boots, so INFO not ERROR.
        logger.info(
            "Ollama not reachable", extra={"event": "health_check", "code": type(exc).__name__}
        )
        return False

    return any(_model_matches(model, m.get("name", "")) for m in models)


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report backend status, the configured provider/model, and model readiness."""
    if settings.llm_provider == "mock":
        # The mock provider needs no model, so it is always ready.
        ready = True
        model = "mock"
    else:
        ready = await ollama_model_ready(settings.ollama_base_url, settings.ollama_model)
        model = settings.ollama_model

    return HealthResponse(
        status="ok" if ready else "degraded",
        provider=settings.llm_provider,
        model=model,
        model_ready=ready,
    )
