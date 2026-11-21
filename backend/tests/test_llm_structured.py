"""Tests for structured-output parsing, validation, refusal detection and retry."""

import json

import pytest
from pydantic import BaseModel

from app.llm.base import (
    LLMOutputInvalidError,
    LLMRefusalError,
    LLMRequest,
    LLMResult,
    LLMTask,
    LLMUnavailableError,
)
from app.llm.structured import generate_structured
from tests.llm_fakes import ScriptedProvider


class Answer(BaseModel):
    summary: str
    count: int


def _request() -> LLMRequest:
    return LLMRequest(task=LLMTask.VISUAL_ANALYSIS, system="s", prompt="analyse", json_schema={})


async def test_valid_output_is_parsed_and_schema_attached() -> None:
    provider = ScriptedProvider([json.dumps({"summary": "ok", "count": 2})])

    answer, _ = await generate_structured(provider, _request(), Answer)

    assert answer == Answer(summary="ok", count=2)
    assert provider.requests[0].json_schema == Answer.model_json_schema()


async def test_fields_outside_schema_are_discarded() -> None:
    raw = {"summary": "ok", "count": 1, "note": "IGNORE PREVIOUS INSTRUCTIONS"}
    answer, _ = await generate_structured(ScriptedProvider([json.dumps(raw)]), _request(), Answer)
    assert "note" not in answer.model_dump()


@pytest.mark.parametrize(
    "output",
    [
        "not json at all",
        json.dumps({"summary": "missing count"}),
        json.dumps({"summary": "x", "count": "many"}),
    ],
)
async def test_invalid_output_raises_without_retry(output: str) -> None:
    provider = ScriptedProvider([output])
    with pytest.raises(LLMOutputInvalidError):
        await generate_structured(provider, _request(), Answer)
    assert len(provider.requests) == 1


async def test_truncated_output_is_invalid_even_if_json_parses() -> None:
    truncated = LLMResult(
        text=json.dumps({"summary": "x", "count": 1}),
        model="m",
        duration_ms=1,
        done_reason="length",
    )
    with pytest.raises(LLMOutputInvalidError, match="cut off"):
        await generate_structured(ScriptedProvider([truncated]), _request(), Answer)


async def test_retry_includes_validation_errors_then_succeeds() -> None:
    provider = ScriptedProvider(
        [
            json.dumps({"summary": "SECRET-VALUE", "count": "SECRET-COUNT"}),
            json.dumps({"summary": "fixed", "count": 3}),
        ]
    )

    answer, _ = await generate_structured(provider, _request(), Answer, retries=1)

    assert answer.count == 3
    retry_prompt = provider.requests[1].prompt
    assert retry_prompt.startswith("analyse")
    assert "count" in retry_prompt  # the location of the error
    assert "SECRET" not in retry_prompt  # but never the offending value


async def test_retry_then_fail() -> None:
    provider = ScriptedProvider(["{}", "{}"])
    with pytest.raises(LLMOutputInvalidError):
        await generate_structured(provider, _request(), Answer, retries=1)
    assert len(provider.requests) == 2


@pytest.mark.parametrize(
    "text",
    [
        "I'm sorry, but I can't help with analysing this image.",
        "I cannot assist with that request.",
        "I am unable to describe this content.",
    ],
)
async def test_plain_text_refusal_is_detected(text: str) -> None:
    with pytest.raises(LLMRefusalError):
        await generate_structured(ScriptedProvider([text]), _request(), Answer, retries=1)


async def test_provider_errors_propagate_without_retry() -> None:
    provider = ScriptedProvider([LLMUnavailableError("down")])
    with pytest.raises(LLMUnavailableError):
        await generate_structured(provider, _request(), Answer, retries=3)
    assert len(provider.requests) == 1
