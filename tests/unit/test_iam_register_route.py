"""PHASE-2 T3: POST /v1/auth/register HTTP adapter (ticket #54).

The route is a thin adapter: parse the typed request, call the facade, answer
the typed flow state. Every expected failure answers the shared error envelope
(api-standards §2) with a stable code and HTTP status. The facade is stubbed
here - the DB-backed behavior is the integration suite's job.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, InvalidPhoneError, SmsDeliveryError
from modules.iam.facade import RegisterPatientResult

_TRACE_ID = "unit-trace-1234abcd"

_RESULT = RegisterPatientResult(
    outcome="sent",
    phone_e164="+919876543210",
    identity_id=7,
    challenge_id=42,
    is_existing=False,
    flow="register",
    expires_in_seconds=300,
    cooldown_remaining_seconds=60,
    attempts_left=5,
)


class StubFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[str] = []
        self.result: RegisterPatientResult | None = _RESULT
        self.error: IamError | None = None

    async def register_patient(self, phone: str) -> RegisterPatientResult:
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


def test_register_returns_flow_state_and_forwards_raw_phone() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/register", json={"phone": "98765 43210"})

    assert response.status_code == 200
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.called_with == ["98765 43210"]


def test_register_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/auth/register" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/register",
        json={"phone": "14445556666"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PHONE_INVALID"
    assert "10-digit Indian mobile number" in body["message"]
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_sms_delivery_failure_answers_502_envelope() -> None:
    facade = StubFacade()
    facade.error = SmsDeliveryError("EXT-001 send failed")
    client = _client_with(facade)

    response = client.post("/v1/auth/register", json={"phone": "9876543210"})

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "SMS_DELIVERY_FAILED"
    assert "EXT-001 send failed" in body["message"]


def test_unexpected_iam_error_answers_500_envelope() -> None:
    facade = StubFacade()
    facade.error = IamError("boom")
    client = _client_with(facade)

    response = client.post("/v1/auth/register", json={"phone": "9876543210"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "Internal identity error" in body["message"]
    assert "boom" not in body["message"]


def test_missing_phone_rejected_at_the_gateway(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/register", json={}, headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"]["errors"][0]["path"] == "phone"
    assert facade.called_with == []
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_empty_phone_rejected_at_the_gateway() -> None:
    client = _client_with(StubFacade())

    response = client.post("/v1/auth/register", json={"phone": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "phone"


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/register", json={"phone": "9876543210", "device": "x"})

    assert response.status_code == 422
    assert facade.called_with == []
