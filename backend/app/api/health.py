"""Health endpoint: reports whether the backend and its model are ready.

The frontend polls this to show a "model downloading / not ready" banner, so it
always returns HTTP 200 with a status body rather than failing when Ollama is
down. ``status`` is ``"ok"`` when the model is usable, otherwise ``"degraded"``.

The readiness check itself lives behind the provider interface
(``LLMProvider.is_ready``), so this route works the same for Ollama and the mock.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_provider
from app.llm.base import LLMProvider

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response body for ``GET /api/health``."""

    status: Literal["ok", "degraded"]
    provider: Literal["ollama", "mock"]
    model: str
    model_ready: bool


@router.get("/health", response_model=HealthResponse)
async def health(provider: LLMProvider = Depends(get_provider)) -> HealthResponse:
    """Report backend status, the configured provider/model, and model readiness."""
    ready = await provider.is_ready()
    return HealthResponse(
        status="ok" if ready else "degraded",
        provider=provider.name,
        model=provider.model,
        model_ready=ready,
    )
