"""Tests for the Ollama provider's request building and error mapping.

No real Ollama: an httpx ``MockTransport`` plays the server.
"""

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMRequest, LLMTask, LLMTimeoutError, LLMUnavailableError
from app.llm.ollama import OllamaProvider


def _request(**overrides: Any) -> LLMRequest:
    base: dict[str, Any] = {
        "task": LLMTask.VISUAL_ANALYSIS,
        "system": "system prompt",
        "prompt": "user prompt",
        "json_schema": {"type": "object"},
        "images": [b"\x89PNG fake"],
        "max_output_tokens": 1234,
    }
    return LLMRequest(**(base | overrides))


def _chat_response(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "qwen3-vl:4b-instruct",
        "message": {"role": "assistant", "content": '{"elements": []}'},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 2175,
        "eval_count": 480,
    }
    return body | overrides


def _provider(tmp_path: Path, handler: Any, **settings: Any) -> OllamaProvider:
    return OllamaProvider(
        Settings(data_dir=tmp_path, **settings), transport=httpx.MockTransport(handler)
    )


async def test_payload_disables_thinking_and_uses_structured_output(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_response())

    provider = _provider(tmp_path, handler, ollama_num_ctx=8192)
    result = await provider.complete(_request())

    body = captured["body"]
    assert captured["path"] == "/api/chat"
    assert body["think"] is False
    assert body["stream"] is False
    assert body["format"] == {"type": "object"}
    assert body["options"]["temperature"] <= 0.2
    assert body["options"]["num_ctx"] == 8192
    assert body["options"]["num_predict"] == 1234
    assert body["messages"][0] == {"role": "system", "content": "system prompt"}
    assert body["messages"][1]["images"] == [base64.b64encode(b"\x89PNG fake").decode()]
    assert result.text == '{"elements": []}'
    assert (result.prompt_tokens, result.output_tokens, result.done_reason) == (2175, 480, "stop")


async def test_no_images_key_when_request_has_no_images(tmp_path: Path) -> None:
    provider = _provider(tmp_path, lambda r: httpx.Response(200, json=_chat_response()))
    payload = provider.build_payload(_request(images=[]))
    assert "images" not in payload["messages"][1]


async def test_timeout_maps_to_llm_timeout(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMTimeoutError):
        await _provider(tmp_path, handler).complete(_request())


async def test_connection_error_maps_to_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError):
        await _provider(tmp_path, handler).complete(_request())


async def test_model_not_found_maps_to_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(LLMUnavailableError, match="404"):
        await _provider(tmp_path, handler).complete(_request())


async def test_unexpected_body_maps_to_unavailable(tmp_path: Path) -> None:
    provider = _provider(tmp_path, lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(LLMUnavailableError):
        await provider.complete(_request())


async def test_log_has_metadata_but_no_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_output = '{"elements": [{"type": "photo", "description": "SECRET-OUTPUT"}]}'
    provider = _provider(
        tmp_path,
        lambda r: httpx.Response(
            200, json=_chat_response(message={"role": "assistant", "content": model_output})
        ),
    )
    with caplog.at_level("INFO"):
        await provider.complete(_request(prompt="SECRET-PROMPT"))

    record = next(r for r in caplog.records if getattr(r, "event", None) == "llm_call")
    assert record.output_tokens == 480  # type: ignore[attr-defined]
    assert "SECRET" not in caplog.text
