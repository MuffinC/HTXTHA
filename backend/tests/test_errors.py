"""Every error response uses the envelope {"error": {code, message, details}}."""

import httpx
from fastapi import Query

from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.main import create_app


def _assert_envelope(body: dict, code: str) -> dict:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    return error


async def _client_with_test_routes(settings: Settings) -> httpx.AsyncClient:
    """App plus throwaway routes that trigger each error path."""
    app = create_app(settings)

    @app.get("/api/_test/api-error")
    async def raise_api_error() -> None:
        raise ApiError(
            ErrorCode.TOO_MANY_FILES, "Too many files.", status_code=400, details={"max_files": 10}
        )

    @app.get("/api/_test/validated")
    async def validated(n: int = Query(..., ge=1)) -> dict:
        return {"n": n}

    @app.get("/api/_test/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    # raise_app_exceptions=False: let the 500 handler respond instead of re-raising in the test.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_unknown_route_returns_not_found_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    _assert_envelope(response.json(), "NOT_FOUND")


async def test_wrong_method_returns_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/health")
    assert response.status_code == 405
    _assert_envelope(response.json(), "METHOD_NOT_ALLOWED")


async def test_api_error_envelope(settings: Settings) -> None:
    async with await _client_with_test_routes(settings) as ac:
        response = await ac.get("/api/_test/api-error")

    assert response.status_code == 400
    error = _assert_envelope(response.json(), "TOO_MANY_FILES")
    assert error["details"] == {"max_files": 10}


async def test_request_validation_envelope_does_not_echo_input(settings: Settings) -> None:
    async with await _client_with_test_routes(settings) as ac:
        response = await ac.get("/api/_test/validated", params={"n": "secret-value"})

    assert response.status_code == 422
    error = _assert_envelope(response.json(), "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["loc"] == ["query", "n"]
    assert "secret-value" not in response.text


async def test_unhandled_exception_envelope_hides_internals(settings: Settings) -> None:
    async with await _client_with_test_routes(settings) as ac:
        response = await ac.get("/api/_test/boom")

    assert response.status_code == 500
    _assert_envelope(response.json(), "INTERNAL_ERROR")
    assert "internal detail" not in response.text
