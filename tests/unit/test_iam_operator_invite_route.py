"""PHASE-5 S9: POST /v1/auth/operator/invite HTTP adapter (ticket #262).

The invite route is a thin adapter: parse the typed request, resolve the
``require_operator`` principal, call the iam facade's ``create_operator_account``,
answer the typed ``OperatorInvitedResult``. The facade is stubbed here - the
DB-backed identity insert + role grant + outbox event belong to the integration
suite. Acceptance criteria pinned here:

- Only an operator-scope MFA-authenticated caller can invite; anon/patient/
  partner is denied 401/403 (``require_operator`` guard).
- The phone is forwarded and the caller's identity defaults the inviter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import OperatorInvitedResult

_SIGNING_KEY = "unit-test-operator-invite-key"

_OPERATOR_ID = 77

_RESULT = OperatorInvitedResult(identity_id=12, phone_e164="+919876543210")


class StubIamFacade:
    """Minimal facade stand-in recording the invite call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result: OperatorInvitedResult | None = _RESULT

    async def create_operator_account(
        self, phone: str, *, invited_by_identity_id: int
    ) -> OperatorInvitedResult:
        self.calls.append({"phone": phone, "invited_by_identity_id": invited_by_identity_id})
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


def test_operator_invites_a_new_phone_with_their_own_identity() -> None:
    facade = StubIamFacade()
    client = _client(facade)
    headers = _bearer(_token())

    response = client.post(
        "/v1/auth/operator/invite", json={"phone": "9876543210"}, headers=headers
    )

    assert response.status_code == 201
    assert response.json() == _RESULT.model_dump(mode="json")
    assert facade.calls == [{"phone": "9876543210", "invited_by_identity_id": _OPERATOR_ID}]


def test_operator_invite_rejects_unknown_fields() -> None:
    facade = StubIamFacade()
    client = _client(facade)
    headers = _bearer(_token())

    response = client.post(
        "/v1/auth/operator/invite",
        json={"phone": "9876543210", "invited_by_identity_id": 22},
        headers=headers,
    )

    assert response.status_code == 422
    assert facade.calls == []


def test_anonymous_invite_denied_with_401() -> None:
    client = _client()

    response = client.post("/v1/auth/operator/invite", json={"phone": "9876543210"})

    assert response.status_code == 401


def test_patient_scope_invite_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="patient"))

    response = client.post(
        "/v1/auth/operator/invite", json={"phone": "9876543210"}, headers=headers
    )

    assert response.status_code == 403


def test_partner_scope_invite_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="partner"))

    response = client.post(
        "/v1/auth/operator/invite", json={"phone": "9876543210"}, headers=headers
    )

    assert response.status_code == 403


def test_operator_invite_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert "/v1/auth/operator/invite" in app.openapi()["paths"]
