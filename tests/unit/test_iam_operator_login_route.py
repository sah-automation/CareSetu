"""PHASE-5 S9: POST /v1/auth/operator/login HTTP adapter (ticket #262).

The login route is a thin adapter: parse the phone + TOTP code, call the iam
facade's ``issue_operator_session`` (the genuine MFA gate, S8/T4), answer the
typed ``SessionResult`` and set the httpOnly session cookie. The facade is
stubbed here; the DB-backed MFA gate and session mint belong to the
integration suite. Acceptance criteria pinned here:

- A presented, verified second factor mints an operator session (200) with the
  session cookie set.
- A missing/absent second factor (stub raising ``OperatorMfaError``) is
  refused 401 with the shared error envelope - the same gate the genuine TOTP
  rejection surfaces.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.exceptions import IamError, OperatorMfaError, SessionIssuanceError
from modules.iam.facade import SessionResult

_SIGNING_KEY = "unit-test-operator-login-key"

_RESULT = SessionResult(
    jwt="header.payload.signature",
    jti="op-jti-1",
    scope="operator",
    identity_id=11,
    expires_in_seconds=900,
    refresh_token="opaque-refresh-token",
)


class StubIamFacade:
    """Minimal facade stand-in recording the login and replaying a canned answer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.result: SessionResult | None = _RESULT
        self.error: IamError | None = None

    async def issue_operator_session(self, phone: str, code: str) -> SessionResult:
        self.calls.append((phone, code))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("stub facade needs a result before the call")
        return self.result


def _client(facade: StubIamFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.iam_facade = facade if facade is not None else StubIamFacade()
    return TestClient(app)


def test_operator_login_with_second_factor_mints_the_session() -> None:
    facade = StubIamFacade()
    client = _client(facade)

    response = client.post(
        "/v1/auth/operator/login", json={"phone": "9876543210", "code": "123456"}
    )

    assert response.status_code == 200
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.calls == [("9876543210", "123456")]


def test_operator_login_success_sets_the_session_cookie() -> None:
    facade = StubIamFacade()
    client = _client(facade)

    response = client.post(
        "/v1/auth/operator/login", json={"phone": "9876543210", "code": "123456"}
    )

    set_cookie = response.headers.get("set-cookie", "")
    assert "caresetu_session=" in set_cookie
    assert "header.payload.signature" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


def test_operator_login_refuses_without_a_verified_second_factor() -> None:
    facade = StubIamFacade()
    facade.error = OperatorMfaError(
        "identity 11 has not completed the MFA second factor; "
        "enroll and verify MFA before issuing an operator session"
    )
    client = _client(facade)

    response = client.post(
        "/v1/auth/operator/login", json={"phone": "9876543210", "code": "123456"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "SESSION_MFA_REQUIRED"
    assert body["trace_id"]


def test_operator_login_wrong_code_is_refused_with_401() -> None:
    facade = StubIamFacade()
    facade.error = OperatorMfaError("TOTP verification failed for identity 11: bad code")
    client = _client(facade)

    response = client.post(
        "/v1/auth/operator/login", json={"phone": "9876543210", "code": "000000"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_MFA_REQUIRED"


def test_operator_login_unknown_phone_stays_409_refused() -> None:
    facade = StubIamFacade()
    facade.error = SessionIssuanceError("no identity for +919876543210")
    client = _client(facade)

    response = client.post(
        "/v1/auth/operator/login", json={"phone": "9876543210", "code": "000000"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SESSION_REFUSED"


def test_operator_login_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    assert "/v1/auth/operator/login" in app.openapi()["paths"]
