"""Context-window budgeting for model calls.

Ollama silently drops the *start* of a prompt that exceeds ``num_ctx``, which
would cut off the system prompt and the security rules first. So every stage
checks its input against a budget before calling the model, and switches to
map-reduce or truncates (with a warning) when it does not fit.

Token counts are estimated, not measured: no tokenizer dependency is needed,
and the estimate is deliberately pessimistic (3 characters per token, where
English averages about 4), so the real prompt is smaller than planned.
"""

import math

CHARS_PER_TOKEN = 3
# System prompt plus task instructions, measured at about 1.2k tokens; rounded up.
PROMPT_OVERHEAD_TOKENS = 1500


def estimate_tokens(text: str) -> int:
    """Pessimistic token estimate for ``text``."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def content_budget_tokens(num_ctx: int, max_output_tokens: int) -> int:
    """Tokens left for document content once instructions and output are reserved."""
    return max(num_ctx - max_output_tokens - PROMPT_OVERHEAD_TOKENS, 0)


def truncate_to_tokens(text: str, tokens: int) -> str:
    """Cut ``text`` so its estimate fits in ``tokens``."""
    return text[: tokens * CHARS_PER_TOKEN]
