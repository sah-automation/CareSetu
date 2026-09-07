"""PHASE-5 review fix (P2/P3, #271): partner self-service status + credential view REST surface.

The two new routes are thin, partner-scoped adapters (US-6/US-7): resolve the
gateway ``Principal`` (via ``require_partner``), call the partner facade, answer
the typed view. The facade is stubbed here; the DB-backed behavior belongs to
the integration suite. Acceptance criteria pinned here:

- ``GET /v1/partner/me`` returns ``{ status, partner_type, round, created_at }``.
- ``GET /v1/partner/me/verification`` returns the current round's review status.
- Both routes are gated by ``require_partner`` (partner scope) - anon/patient/
  operator is denied (401/403).
- Partners in [Registered], [Under Verification], [Active], [Rejected] each get
  a meaningful response on both routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.exceptions import PartnerNotFoundError
from modules.partner.facade import (
    PartnerMeView,
    PartnerVerificationStatusView,
)

_SIGNING_KEY = "unit-test-partner-status-route-key"
_PARTNER_ID = 42
_REGISTERED_AT = datetime(2026, 9, 1, 10, 30, 0, tzinfo=UTC)

_ME_REGISTERED = PartnerMeView(
    partner_id=_PARTNER_ID,
    status="Registered",
    partner_type="doctor",
    round=0,
    created_at=_REGISTERED_AT,
)
_ME_UNDER_VERIFICATION = PartnerMeView(
    partner_id=_PARTNER_ID,
    status="Under Verification",
    partner_type="lab",
    round=1,
    created_at=_REGISTERED_AT,
)
_ME_ACTIVE = PartnerMeView(
    partner_id=_PARTNER_ID,
    status="Active",
    partner_type="chemist",
    round=1,
    created_at=_REGISTERED_AT,
)
_ME_REJECTED = PartnerMeView(
    partner_id=_PARTNER_ID,
    status="Rejected",
    partner_type="doctor",
    round=2,
    created_at=_REGISTERED_AT,
)

_VERIFICATION_REGISTERED = PartnerVerificationStatusView(
    partner_id=_PARTNER_ID,
    round=0,
    status=None,
    decision=None,
    decision_reason=None,
    decided_at=None,
)
_VERIFICATION_UNDER_VERIFICATION = PartnerVerificationStatusView(
    partner_id=_PARTNER_ID,
    round=1,
    status="in_review",
    decision=None,
    decision_reason=None,
    decided_at=None,
)
_VERIFICATION_ACTIVE = PartnerVerificationStatusView(
    partner_id=_PARTNER_ID,
    round=1,
    status="approved",
    decision="approved",
    decision_reason=None,
    decided_at=datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC),
)
_VERIFICATION_REJECTED = PartnerVerificationStatusView(
    partner_id=_PARTNER_ID,
    round=2,
    status="rejected",
    decision="rejected",
    decision_reason="documents unreadable",
    decided_at=datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC),
)

# Which status each view responds for - the four acceptance statuses.
_ME_BY_STATUS: dict[str, PartnerMeView] = {
    "Registered": _ME_REGISTERED,
    "Under Verification": _ME_UNDER_VERIFICATION,
    "Active": _ME_ACTIVE,
    "Rejected": _ME_REJECTED,
}
_VERIFICATION_BY_STATUS: dict[str, PartnerVerificationStatusView] = {
    "Registered": _VERIFICATION_REGISTERED,
    "Under Verification": _VERIFICATION_UNDER_VERIFICATION,
    "Active": _VERIFICATION_ACTIVE,
    "Rejected": _VERIFICATION_REJECTED,
}


class StubPartnerFacade:
    """Minimal facade stand-in recording calls and replaying canned views."""

    def __init__(self, status: str = "Active") -> None:
        self.calls: list[dict[str, object]] = []
        self.status = status
        self.me = _ME_BY_STATUS[status]
        self.verification = _VERIFICATION_BY_STATUS[status]

    async def get_my_status(self, identity_id: int) -> PartnerMeView:
        self.calls.append({"method": "get_my_status", "identity_id": identity_id})
        return self.me

    async def get_my_verification(self, identity_id: int) -> PartnerVerificationStatusView:
        self.calls.append({"method": "get_my_verification", "identity_id": identity_id})
        return self.verification


def _token(*, scope: str = "partner", subject_id: int = 7) -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubPartnerFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.partner_facade = facade if facade is not None else StubPartnerFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -- GET /v1/partner/me -------------------------------------------------------


def test_me_returns_registered_status_for_registered_partner() -> None:
    facade = StubPartnerFacade("Registered")
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _ME_REGISTERED.model_dump(mode="json")
    assert facade.calls == [{"method": "get_my_status", "identity_id": 7}]


def test_me_returns_under_verification_status() -> None:
    facade = StubPartnerFacade("Under Verification")
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _ME_UNDER_VERIFICATION.model_dump(mode="json")


def test_me_returns_active_status() -> None:
    facade = StubPartnerFacade("Active")
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _ME_ACTIVE.model_dump(mode="json")


def test_me_returns_rejected_status() -> None:
    facade = StubPartnerFacade("Rejected")
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _ME_REJECTED.model_dump(mode="json")


def test_me_resolves_on_authenticated_identity_only() -> None:
    facade = StubPartnerFacade("Active")
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token(subject_id=99)))

    assert response.status_code == 200
    assert facade.calls == [{"method": "get_my_status", "identity_id": 99}]


# -- GET /v1/partner/me/verification ------------------------------------------


def test_me_verification_under_review_for_under_verification_partner() -> None:
    facade = StubPartnerFacade("Under Verification")
    client = _client(facade)

    response = client.get("/v1/partner/me/verification", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _VERIFICATION_UNDER_VERIFICATION.model_dump(mode="json")
    assert facade.calls == [{"method": "get_my_verification", "identity_id": 7}]


def test_me_verification_no_round_for_registered_partner() -> None:
    facade = StubPartnerFacade("Registered")
    client = _client(facade)

    response = client.get("/v1/partner/me/verification", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _VERIFICATION_REGISTERED.model_dump(mode="json")


def test_me_verification_approved_for_active_partner() -> None:
    facade = StubPartnerFacade("Active")
    client = _client(facade)

    response = client.get("/v1/partner/me/verification", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _VERIFICATION_ACTIVE.model_dump(mode="json")


def test_me_verification_rejected_reason_for_rejected_partner() -> None:
    facade = StubPartnerFacade("Rejected")
    client = _client(facade)

    response = client.get("/v1/partner/me/verification", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _VERIFICATION_REJECTED.model_dump(mode="json")


# -- Gateway / RBAC gating ----------------------------------------------------


def test_status_routes_require_partner_scope() -> None:
    client = _client()

    # Anonymous: 401 on both.
    assert client.get("/v1/partner/me").status_code == 401
    assert client.get("/v1/partner/me/verification").status_code == 401

    # Operator scope: 403 (not a partner principal).
    op_headers = _bearer(_token(scope="operator"))
    assert client.get("/v1/partner/me", headers=op_headers).status_code == 403
    assert client.get("/v1/partner/me/verification", headers=op_headers).status_code == 403

    # Patient scope: 403.
    pt_headers = _bearer(_token(scope="patient"))
    assert client.get("/v1/partner/me", headers=pt_headers).status_code == 403
    assert client.get("/v1/partner/me/verification", headers=pt_headers).status_code == 403


def test_status_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/v1/partner/me" in paths
    assert "/v1/partner/me/verification" in paths


# -- Unknown identity ----------------------------------------------------------


def test_status_routes_unknown_identity_maps_to_internal() -> None:
    facade = StubPartnerFacade("Active")

    async def raise_not_found(identity_id: int) -> PartnerMeView:
        facade.calls.append({"method": "get_my_status", "identity_id": identity_id})
        raise PartnerNotFoundError(identity_id)

    facade.get_my_status = raise_not_found  # type: ignore[method-assign]
    client = _client(facade)

    response = client.get("/v1/partner/me", headers=_bearer(_token()))

    assert response.status_code == 500
    assert response.json()["code"] == "PARTNER_INTERNAL"


def test_verification_unknown_identity_maps_to_internal() -> None:
    facade = StubPartnerFacade("Active")

    async def raise_not_found(identity_id: int) -> PartnerVerificationStatusView:
        facade.calls.append({"method": "get_my_verification", "identity_id": identity_id})
        raise PartnerNotFoundError(identity_id)

    facade.get_my_verification = raise_not_found  # type: ignore[method-assign]
    client = _client(facade)

    response = client.get("/v1/partner/me/verification", headers=_bearer(_token()))

    assert response.status_code == 500
    assert response.json()["code"] == "PARTNER_INTERNAL"
