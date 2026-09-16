"""PHASE-8.1 T07: GET /v1/intake/review-queue doctor route (ticket #447).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner, call the intake facade's ``list_review_queue``, answer
the typed review-queue shape. Both facades are stubbed here - the DB-backed
queue behavior is the facade suite's job. Every expected failure answers
the shared error envelope (api-standards S2). Doctor RBAC is partner scope +
``partner_type == "doctor"``: unauthenticated (401), patient (403), and
non-doctor partner scopes (403) are rejected at the edge.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.intake.intake_models import ReviewQueueItem
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-review-queue-route-signing-key"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_QUEUE_ITEM_1 = ReviewQueueItem(
    pre_summary_id=2,
    intake_id=20,
    structuring_confidence=0.55,
    low_confidence=True,
    review_state="draft",
    created_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    updated_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
)

_QUEUE_ITEM_2 = ReviewQueueItem(
    pre_summary_id=1,
    intake_id=10,
    structuring_confidence=0.82,
    low_confidence=False,
    review_state="draft",
    created_at=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
    updated_at=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
)


def _token(*, subject_id: int = _DOCTOR_IDENTITY, scope: str = "partner") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class StubIntakeFacade:
    """Minimal intake facade stand-in recording calls and replaying a canned answer."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []
        self.queue_result: list[ReviewQueueItem] = [_QUEUE_ITEM_1, _QUEUE_ITEM_2]

    async def list_review_queue(self, **kwargs: object) -> list[ReviewQueueItem]:
        self.called_with.append(dict(kwargs))
        return self.queue_result


class StubPartnerFacade:
    """Minimal partner facade stand-in resolving the caller's partner profile."""

    def __init__(self, partner_type: str = "doctor") -> None:
        self.partner_type = partner_type

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        return PartnerView(
            partner_id=_PARTNER_ID,
            partner_type=self.partner_type,
            status="Active",
            round=2,
        )


def _client(
    intake_facade: StubIntakeFacade | None = None,
    partner_facade: StubPartnerFacade | None = None,
) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.intake_facade = intake_facade if intake_facade is not None else StubIntakeFacade()
    app.state.partner_facade = partner_facade if partner_facade is not None else StubPartnerFacade()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_review_queue_returns_assigned_awaiting_review_with_confidence_flags() -> None:
    client = _client()

    response = client.get(
        "/v1/intake/review-queue",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["pre_summary_id"] == _QUEUE_ITEM_1.pre_summary_id
    assert body[0]["low_confidence"] is True
    assert body[0]["structuring_confidence"] == 0.55
    assert body[1]["low_confidence"] is False
    assert body[1]["structuring_confidence"] == 0.82


def test_review_queue_empty_list_when_no_items() -> None:
    intake_facade = StubIntakeFacade()
    intake_facade.queue_result = []
    client = _client(intake_facade)

    response = client.get(
        "/v1/intake/review-queue",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_review_queue_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get("/v1/intake/review-queue")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_review_queue_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get(
        "/v1/intake/review-queue",
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_review_queue_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.get(
        "/v1/intake/review-queue",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_review_queue_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/intake/review-queue" in app.openapi()["paths"]
