"""PHASE-2-5 T1: POST /v1/auth/refresh HTTP adapter (ticket #147).

The route is a thin adapter: parse the typed request, call the facade's
``refresh_session``, answer the typed session result with the JWT also set
as an httpOnly cookie. The facade is stubbed here - the DB-backed behavior
is the integration suite's job.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from modules.iam.domain.exceptions import (
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
)
from modules.iam.facade import SessionResult

_TRACE_ID = "unit-trace-refresh-abcd"

_RESULT = SessionResult(
    jwt="header.payload.signature",
    jti="refresh-jti-123",
    scope="patient",
    identity_id=7,
    expires_in_seconds=900,
    refresh_token="new-opaque-refresh-token",
)


class StubRefreshFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[str] = []
        self.result: SessionResult | None = _RESULT
        self.error: Exception | None = None

    async def refresh_session(self, refresh_token: str) -> SessionResult:
        self.called_with.append(refresh_token)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("stub facade needs a result before the call")
        return self.result


def _client_with(facade: StubRefreshFacade) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    return TestClient(app)


def _assert_iam_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    assert any(
        "iam_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


def test_refresh_returns_rotated_session_and_forwards_token() -> None:
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/refresh", json={"refresh_token": "old-opaque-token"})

    assert response.status_code == 200
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.called_with == ["old-opaque-token"]


def test_refresh_sets_jwt_cookie() -> None:
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/refresh", json={"refresh_token": "old-opaque-token"})

    set_cookie = response.headers.get("set-cookie", "")
    assert "caresetu_session=" in set_cookie
    assert "header.payload.signature" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


def test_refresh_jwt_cookie_max_age_matches_token_ttl() -> None:
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/refresh", json={"refresh_token": "old-opaque-token"})

    set_cookie = response.headers.get("set-cookie", "")
    assert "max-age=900" in set_cookie.lower()


def test_unknown_refresh_token_rejected_with_401(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubRefreshFacade()
    facade.error = RefreshTokenUnknownError("no session matches this refresh token")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "unknown-token"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "REFRESH_TOKEN_UNKNOWN"
    assert body["trace_id"] == _TRACE_ID
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_expired_refresh_token_rejected_with_401(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubRefreshFacade()
    facade.error = RefreshTokenExpiredError("this refresh token has expired")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "expired-token"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "REFRESH_TOKEN_EXPIRED"
    assert body["trace_id"] == _TRACE_ID


def test_revoked_refresh_token_rejected_with_401(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubRefreshFacade()
    facade.error = RefreshTokenRevokedError("this refresh token was already used")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "revoked-token"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "REFRESH_TOKEN_REVOKED"
    assert body["trace_id"] == _TRACE_ID


def test_missing_refresh_token_rejected_at_the_gateway(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/refresh", json={}, headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"]["errors"][0]["path"] == "refresh_token"
    assert facade.called_with == []


def test_empty_refresh_token_rejected_at_the_gateway() -> None:
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/refresh", json={"refresh_token": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "refresh_token"


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubRefreshFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "valid-token", "extra": "field"},
    )

    assert response.status_code == 422
    assert facade.called_with == []


def test_refresh_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    assert "/v1/auth/refresh" in app.openapi()["paths"]
