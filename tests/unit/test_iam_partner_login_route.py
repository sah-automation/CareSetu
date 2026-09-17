"""F014-T02 #462: POST /v1/auth/partner/login HTTP adapter (ADR-0016).

The route is a thin adapter: parse the typed request, wire the partner-profile
gate at the composition boundary (``resolve_partner_id_by_identity``), call the
iam facade, return the typed outcome the staff login page renders (``sent``
with the fresh challenge fields, or the refuse states
``no_account``/``cooldown``/``locked``/``suspended``). Every expected failure
answers the shared error envelope (api-standards §2). The facade is stubbed
here - the DB-backed behaviors (no identity row created on refusal, no SMS on
refusal, cooldown/lockout/suspended precedence) are the facade unit and
integration suites' job; this file pins the route seam.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.gateway.idempotency import IdempotencyStore
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, InvalidPhoneError
from modules.iam.facade import PartnerLoginOtpResult

_PHONE = "+919876543210"
_TRACE_ID = "unit-trace-1234abcd"


def _result(outcome: str, **extra: object) -> PartnerLoginOtpResult:
    base: dict[str, object] = {"outcome": outcome, "phone_e164": _PHONE}
    base.update(extra)
    return PartnerLoginOtpResult.model_validate(base)


class StubFacade:
    """Minimal iam facade stand-in recording the call and replaying a canned answer.

    Tracks every method the route could reach so a test can assert only the
    partner-login mutation ran - notably that no identity-creation path
    (``register_patient``) was ever invoked.
    """

    def __init__(self) -> None:
        self.called: list[tuple[str, object]] = []
        self.result: PartnerLoginOtpResult = _result(
            "sent", challenge_id=42, expires_in_seconds=300
        )
        self.error: IamError | None = None

    async def partner_login(self, phone: str, partner_gate: object) -> PartnerLoginOtpResult:
        self.called.append((phone, partner_gate))
        if self.error is not None:
            raise self.error
        return self.result

    async def register_patient(self, phone: str) -> object:
        self.called.append(("register_patient", phone))
        raise AssertionError("partner login must never create an identity")


class PartnerProfileStub:
    """Partner-facade stand-in behind the login gate (identity -> profile id).

    The ``resolve_partner_id_by_identity`` seam is the ONLY partner surface the
    route is allowed to reach (module isolation, ADR-0003).
    """

    def __init__(self, partner_id: int | None = 3) -> None:
        self.partner_id = partner_id
        self.gate_calls: list[int] = []

    async def resolve_partner_id_by_identity(self, identity_id: int) -> int | None:
        self.gate_calls.append(identity_id)
        return self.partner_id


def _client_with(facade: StubFacade, partner: PartnerProfileStub) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    app.state.partner_facade = partner
    return TestClient(app)


def _assert_iam_rejection_logged(caplog: pytest.LogCaptureFixture, trace_id: str) -> None:
    """One ``iam_rejection`` line carries the same id as the envelope."""
    assert any(
        "iam_rejection" in record.getMessage() and f"trace_id={trace_id}" in record.getMessage()
        for record in caplog.records
    )


def test_partner_login_sent_forwards_phone_and_gate() -> None:
    facade = StubFacade()
    facade.result = _result(
        "sent",
        challenge_id=42,
        expires_in_seconds=300,
        cooldown_remaining_seconds=60,
        attempts_left=5,
    )
    partner = PartnerProfileStub()
    client = _client_with(facade, partner)

    response = client.post("/v1/auth/partner/login", json={"phone": "98765 43210"})

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "sent",
        "phone_e164": _PHONE,
        "challenge_id": 42,
        "expires_in_seconds": 300,
        "cooldown_remaining_seconds": 60,
        "attempts_left": 5,
        "lockout_remaining_seconds": None,
    }
    # the route wired the partner facade's resolve seam as the gate port and
    # reached only the partner-login mutation.
    assert len(facade.called) == 1
    raw_phone, gate = facade.called[0]
    assert raw_phone == "98765 43210"
    asyncio.run(gate(7))
    assert partner.gate_calls == [7]


def test_no_account_refusal_never_creates_an_identity() -> None:
    facade = StubFacade()
    facade.result = _result("no_account")
    partner = PartnerProfileStub(partner_id=None)
    client = _client_with(facade, partner)

    response = client.post("/v1/auth/partner/login", json={"phone": "9876543210"})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "no_account"
    assert body["phone_e164"] == _PHONE
    # no registration/identity path was reached on the seam - only the
    # partner-login mutation (an identity create would trip the stub).
    assert len(facade.called) == 1
    assert facade.called[0][0] == "9876543210"
    asyncio.run(facade.called[0][1](7))
    assert partner.gate_calls == [7]


def test_cooldown_locked_suspended_outcomes_render_countdowns() -> None:
    cases = [
        _result("cooldown", cooldown_remaining_seconds=30),
        _result("locked", lockout_remaining_seconds=812),
        _result("suspended"),
    ]
    for canned in cases:
        facade = StubFacade()
        facade.result = canned
        client = _client_with(facade, PartnerProfileStub())

        response = client.post("/v1/auth/partner/login", json={"phone": "9876543210"})

        assert response.status_code == 200
        assert response.json()["outcome"] == canned.outcome


def test_partner_login_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/auth/partner/login" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    facade = StubFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade, PartnerProfileStub())

    response = client.post(
        "/v1/auth/partner/login",
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


def test_unexpected_iam_error_answers_500_envelope() -> None:
    facade = StubFacade()
    facade.error = IamError("boom")
    client = _client_with(facade, PartnerProfileStub())

    response = client.post("/v1/auth/partner/login", json={"phone": "9876543210"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "Internal identity error" in body["message"]
    assert "boom" not in body["message"]


def test_missing_phone_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade, PartnerProfileStub())

    response = client.post("/v1/auth/partner/login", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "phone"
    assert facade.called == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade, PartnerProfileStub())

    response = client.post("/v1/auth/partner/login", json={"phone": "9876543210", "device": "x"})

    assert response.status_code == 422
    assert facade.called == []


# ---------------------------------------------------------------------------
# Idempotency-Key (api-standards §5, PHASE-2 REM T11 #80)
# ---------------------------------------------------------------------------


def test_partner_login_replays_same_key_without_second_facade_call() -> None:
    facade = StubFacade()
    client = _client_with(facade, PartnerProfileStub())
    headers = {"Idempotency-Key": "partner-login-retry-123"}

    first = client.post("/v1/auth/partner/login", json={"phone": "9876543210"}, headers=headers)
    replay = client.post("/v1/auth/partner/login", json={"phone": "9876543210"}, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(facade.called) == 1


def test_partner_login_different_keys_execute_each_mutation() -> None:
    facade = StubFacade()
    client = _client_with(facade, PartnerProfileStub())

    client.post(
        "/v1/auth/partner/login", json={"phone": "9876543210"}, headers={"Idempotency-Key": "k-1"}
    )
    client.post(
        "/v1/auth/partner/login", json={"phone": "9876543210"}, headers={"Idempotency-Key": "k-2"}
    )

    assert len(facade.called) == 2


def test_partner_login_replayed_key_expired_by_ttl_reexecutes(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    facade = StubFacade()
    app = create_app()
    app.state.iam_facade = facade
    app.state.partner_facade = PartnerProfileStub()
    app.state.idempotency_store = store
    client = TestClient(app)
    headers = {"Idempotency-Key": "partner-login-retry-123"}

    client.post("/v1/auth/partner/login", json={"phone": "9876543210"}, headers=headers)
    fake_clock.advance(301)
    client.post("/v1/auth/partner/login", json={"phone": "9876543210"}, headers=headers)

    assert len(facade.called) == 2
