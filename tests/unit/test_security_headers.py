"""TEST-B2 (#136): NFR-SEC-001 transport-posture response headers.

The boundary security posture gate (``scripts/security_posture.py``) asserts
HSTS and ``X-Content-Type-Options`` against the live URLs. This test pins the
backend half of that contract at the app level: every response the app emits -
the 200 health route, a gateway 401 rejection, and a router 404 - carries the
pair, and an upstream value already on a response is preserved rather than
clobbered (``setdefault`` semantics).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.gateway.security_headers import (
    _HSTS_VALUE,
    _X_CONTENT_TYPE_OPTIONS_VALUE,
    SecurityHeadersMiddleware,
)
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_response_carries_the_transport_posture_headers() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.headers.get("strict-transport-security") == _HSTS_VALUE
    assert response.headers.get("x-content-type-options") == _X_CONTENT_TYPE_OPTIONS_VALUE


def test_gateway_rejection_carries_the_transport_posture_headers() -> None:
    response = _client().get("/v1/me")

    assert response.status_code == 401
    assert response.headers.get("strict-transport-security") == _HSTS_VALUE
    assert response.headers.get("x-content-type-options") == _X_CONTENT_TYPE_OPTIONS_VALUE


def test_router_404_carries_the_transport_posture_headers() -> None:
    response = _client().get("/no-such-route")

    assert response.status_code == 404
    assert response.headers.get("strict-transport-security") == _HSTS_VALUE
    assert response.headers.get("x-content-type-options") == _X_CONTENT_TYPE_OPTIONS_VALUE


def test_hsts_value_meets_the_posture_floor() -> None:
    max_age = int(_HSTS_VALUE.split("max-age=")[1].split(";")[0].strip())

    assert "includeSubDomains" in _HSTS_VALUE
    assert max_age >= 15552000


async def test_existing_upstream_header_is_preserved_not_clobbered() -> None:
    """``setdefault`` honours a value already present on the response.

    Driven at the middleware level (like the per-IP rate-limit test in
    ``test_gateway.py``): a stub ``call_next`` answers with its own HSTS value
    and the middleware must keep it, only adding the missing pair.
    """
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    upstream = "max-age=99999999; preload"
    middleware = SecurityHeadersMiddleware(app=None)

    async def stub_call_next(request: Request) -> JSONResponse:
        del request  # the stub never inspects the request
        return JSONResponse({"ok": "yes"}, headers={"Strict-Transport-Security": upstream})

    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/probe",
            "raw_path": b"/probe",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )

    result = await middleware.dispatch(request, stub_call_next)

    assert result.headers.get("Strict-Transport-Security") == upstream
    assert result.headers.get("X-Content-Type-Options") == _X_CONTENT_TYPE_OPTIONS_VALUE
