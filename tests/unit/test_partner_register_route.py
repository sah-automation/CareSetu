"""PHASE-5 T05: POST /v1/partner/register HTTP adapter (ticket #249).

The route is a thin adapter: parse the typed request, call the partner facade,
answer the typed registration result. The facade is stubbed here - the DB-backed
behavior (sync account creation, open/duplicate profile handling) is the
integration suite's job. Every expected failure answers the shared error
envelope (api-standards §2). The pre-activation scope guarantee - a partner
cannot touch patient-facing routes - is enforced by the existing
``require_patient`` gate (only a patient-scoped principal is admitted), so the
registration route needs no RBAC of its own.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import InvalidPhoneError
from modules.partner.domain.exceptions import PartnerError
from modules.partner.facade import RegisterPartnerResult

_TRACE_ID = "unit-trace-partner-9000"

_NEW_RESULT = RegisterPartnerResult(
    partner_id=11,
    identity_id=8,
    partner_type="doctor",
    status="Registered",
    round=0,
    created=True,
)

_DUP_RESULT = RegisterPartnerResult(
    partner_id=11,
    identity_id=8,
    partner_type="doctor",
    status="Registered",
    round=0,
    created=False,
)

_BODY = {
    "phone": "9876543210",
    "partner_type": "doctor",
    "practice_address": "Station Road, Daltonganj",
    "practice_latitude": 24.04,
    "practice_longitude": 84.07,
}


class StubPartnerFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []
        self.result: RegisterPartnerResult | None = _NEW_RESULT
        self.error: Exception | None = None

    async def register(self, **kwargs: object) -> RegisterPartnerResult:
        self.called_with.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("stub facade needs a result before the call")
        return self.result


def _client_with(facade: StubPartnerFacade) -> TestClient:
    app = create_app()
    app.state.partner_facade = facade
    return TestClient(app)


def _assert_partner_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    assert any(
        "partner_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


def test_register_returns_opened_profile_and_forwards_typed_fields() -> None:
    facade = StubPartnerFacade()
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json=_BODY)

    assert response.status_code == 200
    assert response.json() == _NEW_RESULT.model_dump(mode="json")
    assert facade.called_with == [
        {
            "phone": "9876543210",
            "partner_type": "doctor",
            "practice_address": "Station Road, Daltonganj",
            "practice_latitude": 24.04,
            "practice_longitude": 84.07,
            "service_area_id": None,
        }
    ]


def test_register_duplicate_phone_returns_existing_status() -> None:
    facade = StubPartnerFacade()
    facade.result = _DUP_RESULT
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json=_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["status"] == "Registered"
    assert body["partner_id"] == 11


def test_register_forwards_optional_service_area_id() -> None:
    facade = StubPartnerFacade()
    client = _client_with(facade)
    body = {**_BODY, "service_area_id": 1, "partner_type": "chemist"}

    response = client.post("/v1/partner/register", json=body)

    assert response.status_code == 200
    assert facade.called_with[0]["service_area_id"] == 1
    assert facade.called_with[0]["partner_type"] == "chemist"


def test_register_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/partner/register" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope_via_iam_handler() -> None:
    """Invalid phone surfaces as PHONE_INVALID 422 via the iam seam's handler."""
    facade = StubPartnerFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json=_BODY, headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PHONE_INVALID"
    assert "10-digit Indian mobile number" in body["message"]
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


def test_unexpected_partner_error_answers_500_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubPartnerFacade()
    facade.error = PartnerError("boom")
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json=_BODY, headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "PARTNER_INTERNAL"
    assert "Internal partner error" in body["message"]
    assert "boom" not in body["message"]
    assert body["trace_id"] == _TRACE_ID
    _assert_partner_rejection_logged(caplog, _TRACE_ID)


def test_missing_required_field_rejected_at_the_gateway() -> None:
    facade = StubPartnerFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/partner/register",
        json={"phone": "9876543210"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == _TRACE_ID
    assert facade.called_with == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubPartnerFacade()
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json={**_BODY, "invite_code": "x"})

    assert response.status_code == 422
    assert facade.called_with == []


def test_invalid_partner_type_rejected_at_the_gateway() -> None:
    facade = StubPartnerFacade()
    client = _client_with(facade)

    response = client.post("/v1/partner/register", json={**_BODY, "partner_type": "surgeon"})

    assert response.status_code == 422
    assert facade.called_with == []


def test_empty_phone_rejected_at_the_gateway() -> None:
    client = _client_with(StubPartnerFacade())

    response = client.post("/v1/partner/register", json={**_BODY, "phone": ""})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
