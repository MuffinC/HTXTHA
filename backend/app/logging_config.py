"""Structured JSON logging to stdout.

Uses only the standard library (no extra dependency). Each log record becomes
one JSON object per line, which container log collectors can parse directly.

Policy (see docs/ASSUMPTIONS.md): log metadata only. Never log document content
or model outputs, because the documents may contain sensitive information.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Context fields that callers may attach with ``logger.info(..., extra={...})``.
# They are copied into the JSON output when present.
CONTEXT_FIELDS: tuple[str, ...] = (
    "job_id",
    "document_id",
    "stage",
    "duration_ms",
    "event",
    "code",
    "page",
    # Model-call metadata (never prompts or outputs).
    "task",
    "model",
    "prompt_tokens",
    "output_tokens",
)


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise the record, including any known context fields."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger.

    Safe to call more than once (for example, once per test app): existing
    handlers are replaced rather than duplicated.

    Args:
        level: Minimum log level name, e.g. ``"INFO"``.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn's own loggers through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
