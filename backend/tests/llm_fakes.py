"""Test doubles for the LLM layer."""

from app.llm.base import LLMProvider, LLMRequest, LLMResult, LLMTask
from app.llm.mock import MockProvider


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


class RecordingProvider(MockProvider):
    """The mock provider, plus a record of every request and scripted overrides per task.

    ``overrides[task]`` is a list consumed in order: each entry is raw text or an
    exception to raise for the next call of that task. Once a task's list is
    empty, calls fall back to normal mock output.
    """

    def __init__(self, overrides: dict[LLMTask, list[str | Exception]] | None = None) -> None:
        self.overrides = {task: list(items) for task, items in (overrides or {}).items()}
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        pending = self.overrides.get(request.task)
        if pending:
            out = pending.pop(0)
            if isinstance(out, Exception):
                raise out
            return LLMResult(text=out, model=self.model, duration_ms=1, done_reason="stop")
        return await super().complete(request)

    def calls(self, task: LLMTask) -> list[LLMRequest]:
        """Requests made for one task, in order."""
        return [r for r in self.requests if r.task is task]
