"""F014-T03 #463: POST /v1/auth/partner/verify HTTP adapter (ADR-0016).

The route is a thin adapter: parse the typed request, call the iam facade,
return the typed outcome the staff login page renders (``verified``, or the
matching OTP-machine refusal). Every expected failure answers the shared error
envelope (api-standards §2). The facade is stubbed here - the DB-backed
behaviors (challenge consumed exactly once under the ``FOR UPDATE`` lock, the
``phone_verified`` marker written in the same transaction, no patient role
grant / no ``patient.verified`` event, lockout accounting) are the facade unit
and integration suites' job; this file pins the route seam.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.gateway.idempotency import IdempotencyStore
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, InvalidPhoneError
from modules.iam.facade import PartnerVerifyOtpResult

_PHONE = "+919876543210"
_TRACE_ID = "unit-trace-1234abcd"


def _result(outcome: str, **extra: object) -> PartnerVerifyOtpResult:
    base: dict[str, object] = {"outcome": outcome, "phone_e164": _PHONE, "identity_id": 7}
    base.update(extra)
    return PartnerVerifyOtpResult.model_validate(base)


class StubFacade:
    """Minimal iam facade stand-in recording the call and replaying a canned answer.

    Tracks every method the route could reach so a test asserts only the
    partner-verify mutation ran - the patient verify path (``verify_otp``,
    which owns the role grant and the ``patient.verified`` emission) is an
    honesty tripwire: it raises if the partner route ever leaked into it.
    """

    def __init__(self) -> None:
        self.called_with: list[tuple[str, str]] = []
        self.result: PartnerVerifyOtpResult = _result("verified")
        self.error: IamError | None = None

    async def partner_verify(self, phone: str, otp: str) -> PartnerVerifyOtpResult:
        self.called_with.append((phone, otp))
        if self.error is not None:
            raise self.error
        return self.result

    async def verify_otp(self, phone: str, otp: str) -> object:
        self.called_with.append((f"verify_otp:{phone}", otp))
        raise AssertionError("partner verify must never route through the patient verify path")


def _client_with(facade: StubFacade) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    return TestClient(app)


def _client_with_store(facade: StubFacade, store: IdempotencyStore) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    app.state.idempotency_store = store
    return TestClient(app)


def _assert_iam_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    """One ``iam_rejection`` line carries the same id as the envelope."""
    assert any(
        "iam_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


def test_partner_verify_verified_forwards_phone_and_code() -> None:
    facade = StubFacade()
    facade.result = _result("verified")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/partner/verify", json={"phone": "98765 43210", "otp": "654321"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "verified",
        "phone_e164": _PHONE,
        "identity_id": 7,
        "attempts_left": None,
        "lockout_remaining_seconds": None,
    }
    assert facade.called_with == [("98765 43210", "654321")]


def test_partner_verify_never_leaks_into_the_patient_verify_path() -> None:
    facade = StubFacade()
    facade.result = _result("verified")
    client = _client_with(facade)

    response = client.post("/v1/auth/partner/verify", json={"phone": "9876543210", "otp": "123456"})

    assert response.status_code == 200
    # the only mutation reached is the partner-verify one; the patient verify
    # path (role grant, patient.verified, Active transition) was never called.
    assert facade.called_with == [("9876543210", "123456")]


def test_partner_verify_wrong_expired_spent_locked_render_outcomes() -> None:
    cases = [
        _result("wrong_code", attempts_left=3),
        _result("expired"),
        _result("spent", attempts_left=0),
        _result("locked", lockout_remaining_seconds=812),
    ]
    for canned in cases:
        facade = StubFacade()
        facade.result = canned
        client = _client_with(facade)

        response = client.post(
            "/v1/auth/partner/verify", json={"phone": "9876543210", "otp": "654321"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == canned.outcome
        if canned.outcome == "locked":
            assert body["lockout_remaining_seconds"] == 812
        if canned.outcome in ("wrong_code", "spent"):
            assert body["attempts_left"] == canned.attempts_left


def test_partner_verify_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/auth/partner/verify" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/partner/verify",
        json={"phone": "14445556666", "otp": "654321"},
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PHONE_INVALID"
    assert "10-digit Indian mobile number" in body["message"]
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}
    _assert_iam_rejection_logged(caplog, _TRACE_ID)


def test_unexpected_iam_error_answers_500_envelope() -> None:
    facade = StubFacade()
    facade.error = IamError("boom")
    client = _client_with(facade)

    response = client.post("/v1/auth/partner/verify", json={"phone": "9876543210", "otp": "654321"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "Internal identity error" in body["message"]
    assert "boom" not in body["message"]


def test_missing_otp_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/partner/verify", json={"phone": "9876543210"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "otp"
    assert facade.called_with == []


def test_malformed_otp_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/partner/verify", json={"phone": "9876543210", "otp": "12ab34"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.called_with == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321", "device": "x"},
    )

    assert response.status_code == 422
    assert facade.called_with == []


# ---------------------------------------------------------------------------
# Idempotency-Key (api-standards §5, PHASE-2 REM T11 #80)
# ---------------------------------------------------------------------------


def test_partner_verify_replays_same_key_without_reconsuming_the_challenge() -> None:
    facade = StubFacade()
    facade.result = _result("verified")
    client = _client_with(facade)
    headers = {"Idempotency-Key": "partner-verify-retry-123"}

    first = client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers=headers,
    )
    replay = client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers=headers,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert facade.called_with == [("9876543210", "654321")]


def test_partner_verify_different_keys_execute_each_mutation() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers={"Idempotency-Key": "k-1"},
    )
    client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers={"Idempotency-Key": "k-2"},
    )

    assert facade.called_with == [("9876543210", "654321"), ("9876543210", "654321")]


def test_partner_verify_replayed_key_expired_by_ttl_reexecutes(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    facade = StubFacade()
    client = _client_with_store(facade, store)
    headers = {"Idempotency-Key": "partner-verify-retry-123"}

    client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers=headers,
    )
    fake_clock.advance(301)
    client.post(
        "/v1/auth/partner/verify",
        json={"phone": "9876543210", "otp": "654321"},
        headers=headers,
    )

    assert facade.called_with == [("9876543210", "654321"), ("9876543210", "654321")]
