"""Ollama provider: local inference over Ollama's HTTP API.

Uses ``POST /api/chat`` with:

* ``format`` = the Pydantic JSON schema, so decoding is grammar-constrained to
  the schema (structured outputs). The result is still validated afterwards.
* ``think`` = false. The default model is an instruct (non-thinking) variant,
  but the flag is sent explicitly so a thinking model configured by mistake
  does not spend minutes reasoning before answering.
* ``temperature`` 0.1 and a fixed ``seed``: near-deterministic output, so the
  same document gives the same analysis and prompt changes can be compared.
  Not 0, because pure greedy decoding makes small models more prone to
  repetition loops (DECISIONS D-024).

No document content or model output is logged; only timings and token counts.
"""

import base64
import logging
import time
from typing import Any

import httpx

from app.config import Settings
from app.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResult,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

TEMPERATURE = 0.1
SEED = 42
# Keep the model loaded between pages and jobs; reloading costs ~10 s.
KEEP_ALIVE = "15m"
# /api/health is polled every few seconds, so its check must fail fast.
HEALTH_TIMEOUT_SECONDS = 3.0
CONNECT_TIMEOUT_SECONDS = 10.0


def model_matches(requested: str, available: str) -> bool:
    """Return True if an Ollama model name satisfies the requested tag.

    Ollama lists models with an explicit tag (``name:tag``). A request without
    a tag means ``:latest``.
    """
    if ":" not in requested:
        requested = f"{requested}:latest"
    return requested == available


class OllamaProvider(LLMProvider):
    """Calls a local Ollama server."""

    name = "ollama"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        """Create the provider.

        Args:
            settings: Supplies base URL, model, context size and timeout.
            transport: Optional httpx transport, injected by tests.
        """
        self.model = settings.ollama_model
        self._base_url = settings.ollama_base_url
        self._num_ctx = settings.ollama_num_ctx
        self._timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        self._transport = transport

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        # A client per call: calls are long (seconds) and sequential, so connection
        # reuse buys nothing, and there is no client lifecycle to manage.
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout, transport=self._transport
        )

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Build the ``/api/chat`` request body. Public so tests can inspect it."""
        user_message: dict[str, Any] = {"role": "user", "content": request.prompt}
        if request.images:
            user_message["images"] = [
                base64.b64encode(img).decode("ascii") for img in request.images
            ]
        return {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": request.json_schema,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "temperature": TEMPERATURE,
                "seed": SEED,
                "num_ctx": self._num_ctx,
                "num_predict": request.max_output_tokens,
            },
            "messages": [{"role": "system", "content": request.system}, user_message],
        }

    async def complete(self, request: LLMRequest) -> LLMResult:
        """Send one chat request and return the raw JSON text the model produced."""
        started = time.perf_counter()
        try:
            async with self._client(self._timeout) as client:
                response = await client.post("/api/chat", json=self.build_payload(request))
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("The model did not respond within the time limit.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError("Could not reach the Ollama server.") from exc

        if response.status_code != 200:
            # Ollama returns {"error": "..."}; e.g. 404 "model not found". The body is
            # server metadata, not document content, so a short excerpt is safe to keep.
            detail = _error_detail(response)
            raise LLMUnavailableError(f"Ollama returned HTTP {response.status_code}: {detail}")

        try:
            body = response.json()
            text = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMUnavailableError("Ollama returned an unexpected response shape.") from exc

        result = LLMResult(
            text=text,
            model=self.model,
            duration_ms=round((time.perf_counter() - started) * 1000),
            prompt_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"),
            done_reason=body.get("done_reason"),
        )
        logger.info(
            "Model call finished",
            extra={
                "event": "llm_call",
                "task": request.task.value,
                "model": self.model,
                "duration_ms": result.duration_ms,
                "prompt_tokens": result.prompt_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        return result

    async def is_ready(self) -> bool:
        """True if Ollama answers ``GET /api/tags`` and lists the configured model."""
        try:
            async with self._client(HEALTH_TIMEOUT_SECONDS) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            # Expected while Ollama boots, so INFO rather than ERROR.
            logger.info(
                "Ollama not reachable", extra={"event": "health_check", "code": type(exc).__name__}
            )
            return False
        return any(model_matches(self.model, m.get("name", "")) for m in models)


def _error_detail(response: httpx.Response) -> str:
    """Extract Ollama's error string, truncated, for exception messages."""
    try:
        detail = str(response.json().get("error", ""))
    except ValueError:
        detail = ""
    return detail[:200] or "no detail"
