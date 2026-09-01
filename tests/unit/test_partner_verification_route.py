"""PHASE-5 T08: the operator verification console REST surface (ticket #252).

The operator routes are thin adapters: resolve the gateway ``Principal`` (via
``require_operator``), call the partner facade, answer the typed view. The
facade is stubbed here; the DB-backed queue/detail/decision behavior belongs to
the integration suite (``test_partner_verification_queue``). The acceptance
criteria pinned here:

- Only an operator-scope MFA-authenticated caller reaches the console routes;
  partner/patient/anon is denied 403/401 (``require_operator`` guard test).
- Queue lists ``[Under Verification]`` by default, filter/sort params forward.
- Approval/rejection forwards to the facade; rejection REQUIRES a reason (422).
- Opening a detail view emits ``partner.credential_reviewed`` (facade handles it).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.exceptions import (
    InvalidQueueSortError,
    RejectionReasonRequiredError,
)
from modules.partner.facade import (
    CredentialDetail,
    PartnerQueue,
    PartnerQueueItem,
    PartnerVerificationDetail,
    PartnerView,
    VerificationRound,
)

_SIGNING_KEY = "unit-test-partner-verification-key"

_NOW = datetime(2026, 8, 31, 10, 30, 0, tzinfo=UTC)
_OPERATOR_ID = 77

_QUEUE = PartnerQueue(
    items=[
        PartnerQueueItem(
            partner_id=3,
            identity_id=9,
            partner_type="doctor",
            status="Under Verification",
            practice_name="Dr. Arora Clinic",
            practice_address="Station Road, Daltonganj",
            created_at=_NOW,
            round=1,
        )
    ]
)

_DETAIL = PartnerVerificationDetail(
    partner_id=3,
    identity_id=9,
    partner_type="doctor",
    status="Under Verification",
    practice_name="Dr. Arora Clinic",
    practice_address="Station Road, Daltonganj",
    service_area_id=1,
    created_at=_NOW,
    credentials=[
        CredentialDetail(
            credential_id=5,
            credential_type="medical_registration",
            verified=False,
            expires_at=None,
            artifact_refs={"medical_registration_0": "partner/3/enc0"},
        )
    ],
    verification_history=[
        VerificationRound(
            round=1,
            status="queued",
            decision=None,
            decision_reason=None,
            decision_by=None,
            decided_at=None,
            created_at=_NOW,
        )
    ],
)

_APPROVE_RESULT = PartnerView(partner_id=3, status="Active", round=1)
_REJECT_RESULT = PartnerView(partner_id=3, status="Rejected", round=1)


class StubPartnerFacade:
    """Minimal facade stand-in recording the call and replaying a canned view."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.queue: PartnerQueue = _QUEUE
        self.detail: PartnerVerificationDetail = _DETAIL
        self.decision: PartnerView = _APPROVE_RESULT

    async def list_verification_queue(self, **kwargs: object) -> PartnerQueue:
        if kwargs.get("sort_by") == "bogus":
            raise InvalidQueueSortError("bogus")
        self.calls.append({"method": "list_verification_queue", **kwargs})
        return self.queue

    async def get_verification_detail(
        self, partner_id: int, *, actor_id: int
    ) -> PartnerVerificationDetail:
        self.calls.append(
            {"method": "get_verification_detail", "partner_id": partner_id, "actor_id": actor_id}
        )
        return self.detail

    async def operator_decision(
        self,
        partner_id: int,
        decision_by: int,
        *,
        approve: bool,
        reason: str | None = None,
    ) -> PartnerView:
        if not approve and (reason is None or not reason.strip()):
            raise RejectionReasonRequiredError()
        self.calls.append(
            {
                "method": "operator_decision",
                "partner_id": partner_id,
                "decision_by": decision_by,
                "approve": approve,
                "reason": reason,
            }
        )
        return self.decision

    async def grace_lapse(self, partner_id: int) -> PartnerView:
        self.calls.append({"method": "grace_lapse", "partner_id": partner_id})
        return PartnerView(partner_id=partner_id, status="Under Verification", round=1)


def _token(*, scope: str = "operator", subject_id: int = _OPERATOR_ID) -> str:
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


# -- Queue list ----------------------------------------------------------------


def test_operator_queue_lists_under_verification_by_default() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get("/v1/partner/verification-queue", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _QUEUE.model_dump(mode="json")
    assert facade.calls == [
        {
            "method": "list_verification_queue",
            "partner_type": None,
            "status": "Under Verification",
            "sort_by": "registration_age",
        }
    ]


def test_queue_forwards_filters_and_sort() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get(
        "/v1/partner/verification-queue",
        params={"partner_type": "lab", "status": "Rejected", "sort_by": "status"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.calls == [
        {
            "method": "list_verification_queue",
            "partner_type": "lab",
            "status": "Rejected",
            "sort_by": "status",
        }
    ]


def test_unknown_queue_sort_answers_422_invalid_sort() -> None:
    client = _client()

    response = client.get(
        "/v1/partner/verification-queue",
        params={"sort_by": "bogus"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_QUEUE_SORT"


# -- Detail view ---------------------------------------------------------------


def test_operator_detail_forwards_partner_id_and_actor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get("/v1/partner/verification/3", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _DETAIL.model_dump(mode="json")
    assert facade.calls == [
        {"method": "get_verification_detail", "partner_id": 3, "actor_id": _OPERATOR_ID}
    ]


# -- Decision ------------------------------------------------------------------


def test_approve_forwards_to_facade() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.post(
        "/v1/partner/verification/3/decision",
        json={"approve": True},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _APPROVE_RESULT.model_dump(mode="json")
    assert facade.calls == [
        {
            "method": "operator_decision",
            "partner_id": 3,
            "decision_by": _OPERATOR_ID,
            "approve": True,
            "reason": None,
        }
    ]


def test_reject_forwards_reason_to_facade() -> None:
    facade = StubPartnerFacade()
    facade.decision = _REJECT_RESULT
    client = _client(facade)

    response = client.post(
        "/v1/partner/verification/3/decision",
        json={"approve": False, "reason": "documents unreadable"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _REJECT_RESULT.model_dump(mode="json")
    assert facade.calls == [
        {
            "method": "operator_decision",
            "partner_id": 3,
            "decision_by": _OPERATOR_ID,
            "approve": False,
            "reason": "documents unreadable",
        }
    ]


def test_reject_without_reason_answers_422_and_never_forwards() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    for payload in ({"approve": False}, {"approve": False, "reason": ""}):
        response = client.post(
            "/v1/partner/verification/3/decision",
            json=payload,
            headers=_bearer(_token()),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "REJECTION_REASON_REQUIRED"

    assert [c["approve"] for c in facade.calls] == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    client = _client()

    response = client.post(
        "/v1/partner/verification/3/decision",
        json={"approve": True, "bulk": True},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


# -- Grace-window lapse (PHASE-5 T10) --------------------------------------------


def test_grace_lapse_forwards_to_facade() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.post("/v1/partner/verification/3/grace-lapse", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == PartnerView(
        partner_id=3, status="Under Verification", round=1
    ).model_dump(mode="json")
    assert facade.calls == [{"method": "grace_lapse", "partner_id": 3}]


# -- RBAC guard -----------------------------------------------------------------


def test_anonymous_queue_denied_with_401() -> None:
    client = _client()

    assert client.get("/v1/partner/verification-queue").status_code == 401
    assert client.get("/v1/partner/verification/3").status_code == 401
    assert (
        client.post("/v1/partner/verification/3/decision", json={"approve": True}).status_code
        == 401
    )
    assert client.post("/v1/partner/verification/3/grace-lapse").status_code == 401


def test_patient_scope_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="patient"))

    assert client.get("/v1/partner/verification-queue", headers=headers).status_code == 403
    assert client.get("/v1/partner/verification/3", headers=headers).status_code == 403
    assert (
        client.post(
            "/v1/partner/verification/3/decision", json={"approve": True}, headers=headers
        ).status_code
        == 403
    )
    assert client.post("/v1/partner/verification/3/grace-lapse", headers=headers).status_code == 403


def test_partner_scope_denied_with_403() -> None:
    client = _client()
    headers = _bearer(_token(scope="partner"))

    assert client.get("/v1/partner/verification-queue", headers=headers).status_code == 403
    assert (
        client.post(
            "/v1/partner/verification/3/decision", json={"approve": True}, headers=headers
        ).status_code
        == 403
    )
    assert client.post("/v1/partner/verification/3/grace-lapse", headers=headers).status_code == 403


def test_console_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    paths = app.openapi()["paths"]
    assert "/v1/partner/verification-queue" in paths
    assert "/v1/partner/verification/{partner_id}" in paths
    assert "/v1/partner/verification/{partner_id}/decision" in paths
    assert "/v1/partner/verification/{partner_id}/grace-lapse" in paths
