"""Test doubles for the LLM layer."""

from app.llm.base import LLMProvider, LLMRequest, LLMResult


class ScriptedProvider(LLMProvider):
    """Returns pre-set outputs in order and records the requests it received.

    Each output may be raw text (returned with ``done_reason="stop"``), a full
    ``LLMResult``, or an exception instance to raise.
    """

    name = "mock"
    model = "scripted"

    def __init__(self, outputs: list[str | LLMResult | Exception]) -> None:
        self.outputs = list(outputs)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, LLMResult):
            return out
        return LLMResult(text=out, model=self.model, duration_ms=1, done_reason="stop")

    async def is_ready(self) -> bool:
        return True
