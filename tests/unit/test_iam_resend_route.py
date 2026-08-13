"""PHASE-2 T5: POST /v1/auth/resend HTTP adapter (ticket #56).

The route is a thin adapter: parse the typed request, call the facade, return
the typed outcome the PWA renders (``sent`` with the fresh challenge fields, or
the refuse states ``cooldown``/``locked``/``suspended``/``no_identity``). Every
expected failure answers the shared error envelope (api-standards §2). The
facade is stubbed here - the DB-backed behavior, including which outbox rows
each outcome writes, is the integration suite's job.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, InvalidPhoneError
from modules.iam.facade import ResendOtpResult

_PHONE = "+919876543210"


def _result(outcome: str, **extra: object) -> ResendOtpResult:
    base: dict[str, object] = {"outcome": outcome, "phone_e164": _PHONE}
    base.update(extra)
    return ResendOtpResult.model_validate(base)


class StubFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[str] = []
        self.result: ResendOtpResult = _result("sent", challenge_id=42, expires_in_seconds=300)
        self.error: IamError | None = None

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        self.called_with.append(phone)
        if self.error is not None:
            raise self.error
        return self.result


def _client_with(facade: StubFacade) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    return TestClient(app)


def test_resend_sent_forwards_raw_phone_and_returns_challenge_fields() -> None:
    facade = StubFacade()
    facade.result = _result(
        "sent",
        challenge_id=42,
        expires_in_seconds=300,
        cooldown_remaining_seconds=60,
        attempts_left=5,
    )
    client = _client_with(facade)

    response = client.post("/v1/auth/resend", json={"phone": "98765 43210"})

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "sent",
        "phone_e164": _PHONE,
        "challenge_id": 42,
        "expires_in_seconds": 300,
        "cooldown_remaining_seconds": 60,
        "lockout_remaining_seconds": None,
        "attempts_left": 5,
    }
    assert facade.called_with == ["98765 43210"]


def test_cooldown_and_locked_outcomes_render_countdowns() -> None:
    cases = [
        _result("cooldown", cooldown_remaining_seconds=30),
        _result("locked", lockout_remaining_seconds=812),
        _result("suspended"),
        _result("no_identity"),
    ]
    for canned in cases:
        facade = StubFacade()
        facade.result = canned
        client = _client_with(facade)

        response = client.post("/v1/auth/resend", json={"phone": "9876543210"})

        assert response.status_code == 200
        assert response.json()["outcome"] == canned.outcome


def test_resend_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert "/v1/auth/resend" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope() -> None:
    facade = StubFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade)

    response = client.post("/v1/auth/resend", json={"phone": "14445556666"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PHONE_INVALID"
    assert "10-digit Indian mobile number" in body["message"]
    assert isinstance(body["trace_id"], str) and body["trace_id"]
    assert body["details"] == {}


def test_unexpected_iam_error_answers_500_envelope() -> None:
    facade = StubFacade()
    facade.error = IamError("boom")
    client = _client_with(facade)

    response = client.post("/v1/auth/resend", json={"phone": "9876543210"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "Internal identity error" in body["message"]
    assert "boom" not in body["message"]


def test_missing_phone_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/resend", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "phone"
    assert facade.called_with == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/resend", json={"phone": "9876543210", "device": "x"})

    assert response.status_code == 422
    assert facade.called_with == []
