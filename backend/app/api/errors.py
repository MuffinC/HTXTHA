"""Exception handlers that render every error in the standard envelope.

Covers application errors (``ApiError``), FastAPI/Starlette HTTP errors (404,
405, ...), request validation errors (422) and unexpected exceptions (500), so
the client never has to parse more than one error shape.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import ApiError, ErrorCode
from app.schemas.errors import ErrorBody, ErrorEnvelope

logger = logging.getLogger(__name__)

# Map common HTTP statuses raised by the framework to our codes.
_HTTP_STATUS_CODES: dict[int, ErrorCode] = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
}


def error_response(
    status_code: int, code: ErrorCode, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    """Build a ``JSONResponse`` carrying the standard error envelope."""
    envelope = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


async def _handle_api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101 - narrowing for the type checker
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _handle_http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(exc.status_code, code, message)


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    # Report where and why validation failed, but not the submitted values
    # (``input``), which could echo document content back or into logs.
    problems = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return error_response(
        422, ErrorCode.VALIDATION_ERROR, "The request is invalid.", {"errors": problems}
    )


async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    # Log the traceback server-side; never leak internals to the client.
    logger.error("Unhandled exception", exc_info=exc, extra={"event": "unhandled_exception"})
    return error_response(500, ErrorCode.INTERNAL_ERROR, "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    """Attach all error handlers to ``app``."""
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
