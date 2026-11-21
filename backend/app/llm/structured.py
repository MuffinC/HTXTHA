"""Turn a provider's raw text into a validated Pydantic model.

Every model call in the pipeline goes through ``generate_structured``:

1. Attach the schema's JSON schema to the request (Ollama ``format``).
2. Reject truncated output (``done_reason == "length"``).
3. Parse JSON. If the text is not JSON and reads like a refusal
   ("I'm sorry, I can't..."), raise ``LLMRefusalError``.
4. Validate with Pydantic. Fields the schema does not define are dropped, so
   free text outside the schema never reaches the user (CLAUDE.md section 7).
5. Optionally retry with the validation errors in the prompt (stage 3 uses one
   retry, as the spec requires; visual analysis uses none, see DECISIONS D-028).
"""

import json
import logging
import re
from dataclasses import replace

from pydantic import BaseModel, ValidationError

from app.llm.base import (
    LLMOutputInvalidError,
    LLMProvider,
    LLMRefusalError,
    LLMRequest,
    LLMResult,
)
from app.llm.prompts import render_prompt

logger = logging.getLogger(__name__)

# Phrases that mark a plain-text refusal. Only checked when the output is not
# JSON: with Ollama's grammar-constrained decoding a refusal usually arrives
# as a schema field (e.g. ``declined_reason``) instead.
_REFUSAL = re.compile(
    r"\b(?:i(?:'m| am) sorry|i can(?:'|no)t (?:help|assist|comply|analy[sz]e|provide)|"
    r"i(?:'m| am) (?:unable|not able) to|i won'?t be able to|as an ai)\b",
    re.IGNORECASE,
)

# Cap on how many validation errors are fed back into a retry prompt.
MAX_REPORTED_ERRORS = 10


async def generate_structured[T: BaseModel](
    provider: LLMProvider,
    request: LLMRequest,
    schema: type[T],
    *,
    retries: int = 0,
) -> tuple[T, LLMResult]:
    """Call the provider and return output validated against ``schema``.

    Args:
        provider: The LLM provider.
        request: The request; its ``json_schema`` is replaced by ``schema``'s.
        schema: Pydantic model the output must match.
        retries: Extra attempts after invalid output. Each retry appends the
            validation errors (locations and messages only) to the prompt.

    Returns:
        The validated model and the result of the successful call.

    Raises:
        LLMOutputInvalidError: Output still invalid after all attempts.
        LLMRefusalError: The model refused in plain text.
        LLMUnavailableError / LLMTimeoutError: Propagated from the provider.
    """
    request = replace(request, json_schema=schema.model_json_schema())
    attempt_request = request
    for attempt in range(retries + 1):
        result = await provider.complete(attempt_request)
        try:
            return parse_output(result, schema), result
        except LLMOutputInvalidError as exc:
            logger.warning(
                "Model output failed validation (attempt %d of %d)",
                attempt + 1,
                retries + 1,
                extra={"event": "llm_output_invalid", "task": request.task.value},
            )
            if attempt == retries:
                raise
            correction = render_prompt(
                "retry_invalid_output", errors="\n".join(f"- {e}" for e in exc.validation_errors)
            )
            attempt_request = replace(request, prompt=f"{request.prompt}\n\n{correction}")
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


def parse_output[T: BaseModel](result: LLMResult, schema: type[T]) -> T:
    """Parse and validate one raw result. See module docstring for the rules."""
    if result.done_reason == "length":
        raise LLMOutputInvalidError(
            "The model output was cut off at the token limit.",
            ["output truncated: respond more concisely"],
        )
    try:
        data = json.loads(result.text)
    except json.JSONDecodeError as exc:
        if _REFUSAL.search(result.text[:500]):
            raise LLMRefusalError("The model declined to analyse this content.") from exc
        raise LLMOutputInvalidError(
            "The model output was not valid JSON.", ["response was not valid JSON"]
        ) from exc
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputInvalidError(
            "The model output did not match the schema.", _summarise(exc)
        ) from exc


def _summarise(exc: ValidationError) -> list[str]:
    """Location + message for each error. Never includes the offending input value."""
    errors = exc.errors(include_input=False, include_url=False)
    return [
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in errors[:MAX_REPORTED_ERRORS]
    ]
