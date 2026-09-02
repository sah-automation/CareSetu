"""PHASE-5 T09: rejected-partner recovery REST surface (#253).

The recovery routes are thin, partner-scoped adapters: resolve the gateway
``Principal`` (via ``require_partner``), call the partner facade, answer the
typed view. The facade is stubbed here; the DB-backed recovery behavior belongs
to the integration suite. Acceptance criteria pinned here:

- A ``[Rejected]`` partner views their specific rejection reason.
- A partner files the one-time appeal; the facade is the authority on whether it
  is (re)used - the route forwards and answers typed views.
- Only a partner-scope caller reaches the routes; anon/patient/operator is
  denied (401/403) and a non-rejected partner maps to PARTNER_NOT_REJECTED 422.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    PartnerNotRejectedError,
)
from modules.partner.facade import PartnerView, RejectionReasonView

_SIGNING_KEY = "unit-test-partner-rejection-recovery-key"
_PARTNER_ID = 42
_REASON = "documents unreadable"

_REJECTION_VIEW = RejectionReasonView(partner_id=_PARTNER_ID, rejection_reason=_REASON, round=2)
_APPEAL_RESULT = PartnerView(partner_id=_PARTNER_ID, status="Under Verification", round=3)


class StubPartnerFacade:
    """Minimal facade stand-in recording the call and replaying canned views."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.rejection: RejectionReasonView = _REJECTION_VIEW
        self.appeal_result: PartnerView = _APPEAL_RESULT

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        self.calls.append({"method": "resolve_partner", "identity_id": identity_id})
        return PartnerView(partner_id=_PARTNER_ID, status="Rejected", round=2)

    async def get_rejection_reason(self, partner_id: int) -> RejectionReasonView:
        self.calls.append({"method": "get_rejection_reason", "partner_id": partner_id})
        return self.rejection

    async def appeal(self, partner_id: int) -> PartnerView:
        self.calls.append({"method": "appeal", "partner_id": partner_id})
        return self.appeal_result


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


def test_rejected_partner_views_rejection_reason() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get("/v1/partner/rejection-reason", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _REJECTION_VIEW.model_dump(mode="json")
    assert facade.calls == [
        {"method": "resolve_partner", "identity_id": 7},
        {"method": "get_rejection_reason", "partner_id": _PARTNER_ID},
    ]


def test_partner_files_one_time_appeal() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.post("/v1/partner/appeal", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _APPEAL_RESULT.model_dump(mode="json")
    assert facade.calls == [
        {"method": "resolve_partner", "identity_id": 7},
        {"method": "appeal", "partner_id": _PARTNER_ID},
    ]


def test_non_rejected_partner_reason_answers_422_not_rejected() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    # Stub the facade to raise for a non-rejected partner.
    async def raise_not_rejected(partner_id: int) -> RejectionReasonView:
        facade.calls.append({"method": "get_rejection_reason", "partner_id": partner_id})
        raise PartnerNotRejectedError(partner_id, "Active")

    facade.get_rejection_reason = raise_not_rejected  # type: ignore[method-assign]
    response = client.get("/v1/partner/rejection-reason", headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "PARTNER_NOT_REJECTED"


def test_second_appeal_answers_422_already_used() -> None:
    facade = StubPartnerFacade()

    async def raise_used(partner_id: int) -> PartnerView:
        facade.calls.append({"method": "appeal", "partner_id": partner_id})
        raise AppealAlreadyUsedError()

    facade.appeal = raise_used  # type: ignore[method-assign]
    client = _client(facade)

    response = client.post("/v1/partner/appeal", headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "APPEAL_ALREADY_USED"


def test_recovery_routes_require_partner_scope() -> None:
    client = _client()

    # Anonymous: 401 on both.
    assert client.get("/v1/partner/rejection-reason").status_code == 401
    assert client.post("/v1/partner/appeal").status_code == 401

    # Operator scope: 403 (not a partner principal).
    op_headers = _bearer(_token(scope="operator"))
    assert client.get("/v1/partner/rejection-reason", headers=op_headers).status_code == 403
    assert client.post("/v1/partner/appeal", headers=op_headers).status_code == 403

    # Patient scope: 403.
    pt_headers = _bearer(_token(scope="patient"))
    assert client.get("/v1/partner/rejection-reason", headers=pt_headers).status_code == 403
    assert client.post("/v1/partner/appeal", headers=pt_headers).status_code == 403


def test_recovery_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/v1/partner/rejection-reason" in paths
    assert "/v1/partner/appeal" in paths


# -- Idempotency (api-standards 5) ----------------------------------------------


def test_appeal_idempotent_same_key_replays_result() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    key = "appeal-key-1"

    resp1 = client.post(
        "/v1/partner/appeal",
        headers={**_bearer(_token()), "Idempotency-Key": key},
    )
    resp2 = client.post(
        "/v1/partner/appeal",
        headers={**_bearer(_token()), "Idempotency-Key": key},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
    assert len(facade.calls) == 2  # resolve_partner + appeal called once each


def test_appeal_distinct_keys_both_apply() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    resp1 = client.post(
        "/v1/partner/appeal",
        headers={**_bearer(_token()), "Idempotency-Key": "key-1"},
    )
    resp2 = client.post(
        "/v1/partner/appeal",
        headers={**_bearer(_token()), "Idempotency-Key": "key-2"},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(facade.calls) == 4  # resolve_partner + appeal called twice each


def test_appeal_missing_key_still_allows_mutation() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    resp = client.post(
        "/v1/partner/appeal",
        headers=_bearer(_token()),
    )

    assert resp.status_code == 200
    assert len(facade.calls) == 2  # resolve_partner + appeal
