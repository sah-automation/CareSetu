"""PHASE-5 P1: POST /v1/auth/operator/mfa/enroll HTTP adapter (ticket #272).

The enroll route is a thin adapter: resolve the ``require_operator`` principal,
call the iam facade's ``enroll_mfa`` with the caller's identity id, answer the
typed ``EnrollMfaResult``. The facade is stubbed here - the DB-backed secret
generation + encryption + upsert belong to the integration suite. Acceptance
criteria pinned here:

- Only an operator-scope MFA-authenticated caller can enroll; anon/patient/
  partner is denied 401/403 (``require_operator`` guard).
- The caller's own identity id is forwarded to ``enroll_mfa`` and the real
  encrypted-secret result (plaintext secret + provisioning URI) is returned.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import EnrollMfaResult

_SIGNING_KEY = "unit-test-operator-mfa-enroll-key"

_OPERATOR_ID = 77

_RESULT = EnrollMfaResult(
    identity_id=_OPERATOR_ID,
    phone_e164="+919876543210",
    secret="JBSWY3DPEHPK3PXP",
    provisioning_uri="otpauth://totp/CareSetu:%2B919876543210?secret=JBSWY3DPEHPK3PXP",
)


class StubIamFacade:
    """Minimal facade stand-in recording the enroll call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result: EnrollMfaResult | None = _RESULT

    async def enroll_mfa(self, identity_id: int) -> EnrollMfaResult:
        self.calls.append({"identity_id": identity_id})
        if self.result is None:
            raise AssertionError("stub facade needs a result before the call")
        return self.result


def _token(*, scope: str = "operator", subject_id: int = _OPERATOR_ID) -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubIamFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.iam_facade = facade if facade is not None else StubIamFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_operator_enrolls_their_own_mfa_factor() -> None:
    facade = StubIamFacade()
    client = _client(facade)
    headers = _bearer(_token())

    response = client.post("/v1/auth/operator/mfa/enroll", headers=headers)

    assert response.status_code == 200
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.calls == [{"identity_id": _OPERATOR_ID}]


def test_anonymous_enroll_denied_with_401() -> None:
    client = _client()

    response = client.post("/v1/auth/operator/mfa/enroll")

    assert response.status_code == 401


def test_patient_scope_enroll_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="patient"))

    response = client.post("/v1/auth/operator/mfa/enroll", headers=headers)

    assert response.status_code == 403


def test_partner_scope_enroll_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="partner"))

    response = client.post("/v1/auth/operator/mfa/enroll", headers=headers)

    assert response.status_code == 403


def test_operator_enroll_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert "/v1/auth/operator/mfa/enroll" in app.openapi()["paths"]
