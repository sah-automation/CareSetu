"""PHASE-2 T9: POST /v1/auth/session HTTP adapter (ticket #60).

The route is a thin adapter: parse the typed request, call the facade's
``issue_session``, answer the typed session result. The PWA calls it only
after a ``verified`` outcome; the facade refuses an unverified or Suspended
identity with the shared error envelope. The facade is stubbed here - the
DB-backed behavior is the integration suite's job.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, SessionIssuanceError
from modules.iam.facade import IssueSessionResult

_TRACE_ID = "unit-trace-1234abcd"

_RESULT = IssueSessionResult(
    jwt="header.payload.signature",
    jti="abc123",
    scope="patient",
    identity_id=7,
    expires_in_seconds=900,
    refresh_token="opaque-refresh-token",
)


class StubFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[str] = []
        self.result: IssueSessionResult | None = _RESULT
        self.error: IamError | None = None

    async def issue_session(self, phone: str) -> IssueSessionResult:
        self.called_with.append(phone)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("stub facade needs a result before the call")
        return self.result


def _client_with(facade: StubFacade) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    return TestClient(app)


def _assert_iam_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    """One ``iam_rejection`` line carries the same id as the envelope."""
    assert any(
        "iam_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


def test_session_returns_minted_session_and_forwards_raw_phone() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/session", json={"phone": "98765 43210"})

    assert response.status_code == 200
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.called_with == ["98765 43210"]


def test_session_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/auth/session" in app.openapi()["paths"]


def test_unverified_identity_refused_with_409_envelope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    facade.error = SessionIssuanceError(
        "identity 7 is Unverified, not Active; verify the OTP first"
    )
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/session",
        json={"phone": "9876543210"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "SESSION_REFUSED"
    assert "verify the OTP first" in body["message"]
    assert body["trace_id"] == _TRACE_ID
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_missing_phone_rejected_at_the_gateway(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/session", json={}, headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"]["errors"][0]["path"] == "phone"
    assert facade.called_with == []
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_empty_phone_rejected_at_the_gateway() -> None:
    client = _client_with(StubFacade())

    response = client.post("/v1/auth/session", json={"phone": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "phone"


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/session", json={"phone": "9876543210", "device": "x"})

    assert response.status_code == 422
    assert facade.called_with == []
