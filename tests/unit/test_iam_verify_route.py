"""PHASE-2 T4: POST /v1/auth/verify HTTP adapter (ticket #55).

The route is a thin adapter: parse the typed request, call the facade, return
the typed outcome the PWA renders. Every expected failure answers the shared
error envelope (api-standards §2). The facade is stubbed here - the DB-backed
behavior, including which outbox rows each outcome writes, is the integration
suite's job.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.main import create_app
from modules.iam.domain.exceptions import IamError, InvalidPhoneError
from modules.iam.facade import VerifyOtpResult

_PHONE = "+919876543210"


def _result(outcome: str, **extra: object) -> VerifyOtpResult:
    base: dict[str, object] = {"outcome": outcome, "phone_e164": _PHONE, "identity_id": 7}
    base.update(extra)
    return VerifyOtpResult.model_validate(base)


class StubFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[tuple[str, str]] = []
        self.result: VerifyOtpResult = _result("verified")
        self.error: IamError | None = None

    async def verify_otp(self, phone: str, otp: str) -> VerifyOtpResult:
        self.called_with.append((phone, otp))
        if self.error is not None:
            raise self.error
        return self.result


def _client_with(facade: StubFacade) -> TestClient:
    app = create_app()
    app.state.iam_facade = facade
    return TestClient(app)


def test_verify_success_forwards_phone_and_code() -> None:
    facade = StubFacade()
    facade.result = _result("verified")
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "98765 43210", "otp": "654321"})

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "verified",
        "phone_e164": _PHONE,
        "identity_id": 7,
        "attempts_left": None,
        "lockout_remaining_seconds": None,
    }
    assert facade.called_with == [("98765 43210", "654321")]


def test_wrong_code_returns_attempts_left() -> None:
    facade = StubFacade()
    facade.result = _result("wrong_code", attempts_left=3)
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "9876543210", "otp": "111111"})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "wrong_code"
    assert body["attempts_left"] == 3


def test_expired_and_spent_return_request_new_code_outcome() -> None:
    client = _client_with(StubFacade())
    for outcome in ("expired", "spent"):
        facade = StubFacade()
        facade.result = _result(outcome, attempts_left=0 if outcome == "spent" else None)
        client = _client_with(facade)

        response = client.post("/v1/auth/verify", json={"phone": "9876543210", "otp": "654321"})

        assert response.status_code == 200
        assert response.json()["outcome"] == outcome


def test_locked_outcome_renders_the_lockout_countdown() -> None:
    facade = StubFacade()
    facade.result = _result("locked", lockout_remaining_seconds=812)
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "9876543210", "otp": "654321"})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "locked"
    assert body["lockout_remaining_seconds"] == 812


def test_verify_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert "/v1/auth/verify" in app.openapi()["paths"]


def test_invalid_phone_answers_422_envelope() -> None:
    facade = StubFacade()
    facade.error = InvalidPhoneError("phone must be a valid 10-digit Indian mobile number")
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "14445556666", "otp": "654321"})

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

    response = client.post("/v1/auth/verify", json={"phone": "9876543210", "otp": "654321"})

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "boom" not in body["message"]


def test_missing_otp_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "9876543210"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"][0]["path"] == "otp"
    assert facade.called_with == []


def test_malformed_otp_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post("/v1/auth/verify", json={"phone": "9876543210", "otp": "12ab34"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.called_with == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/auth/verify", json={"phone": "9876543210", "otp": "654321", "device": "x"}
    )

    assert response.status_code == 422
    assert facade.called_with == []
