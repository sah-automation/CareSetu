"""PHASE-8.1 T08: GET /v1/intake/{intake_id}/pre-summary/review doctor route (#448, FEAT-008).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner, call the intake facade's ``get_doctor_pre_summary``,
answer the typed pre-summary shape. Both facades are stubbed here - the
DB-backed full-content and assignment-scoping behavior is the facade suite's
job. Every expected failure answers the shared error envelope
(api-standards S2). Doctor RBAC is partner scope + ``partner_type == "doctor"``:
unauthenticated (401), patient (403), and non-doctor partner scopes (403) are
rejected at the edge; an unassigned doctor surfaces the intake 404 (the facade
never reveals an intake assigned to another doctor).
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
from modules.intake.domain.exceptions import IntakeNotFoundError
from modules.intake.intake_models import PreSummaryView
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-pre-summary-route-signing-key"

_TRACE_ID = "unit-trace-doctor-pre-summary-9100"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_PRE_SUMMARY = PreSummaryView(
    pre_summary_id=101,
    intake_id=42,
    structured_fields={
        "chief_complaints": ["headache"],
        "symptoms": ["throbbing in the temples"],
        "duration": "3 days",
    },
    structuring_confidence=0.55,
    low_confidence=True,
    review_state="draft",
    patient_edits=None,
    doctor_corrections=None,
    review_attribution=None,
    reviewed_by=None,
    reviewed_at=None,
    created_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    updated_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
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
        self.pre_summary: PreSummaryView = _PRE_SUMMARY
        self.error: Exception | None = None

    async def get_doctor_pre_summary(self, **kwargs: object) -> PreSummaryView:
        self.called_with.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.pre_summary


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


def test_doctor_pre_summary_returns_full_content() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.get(
        "/v1/intake/42/pre-summary/review",
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pre_summary_id"] == _PRE_SUMMARY.pre_summary_id
    assert body["intake_id"] == 42
    assert body["structured_fields"]["chief_complaints"] == ["headache"]
    assert body["structured_fields"]["symptoms"] == ["throbbing in the temples"]
    assert body["structuring_confidence"] == 0.55
    assert body["low_confidence"] is True
    assert body["review_state"] == "draft"
    assert intake_facade.called_with == [{"intake_id": 42, "doctor_id": _PARTNER_ID}]


def test_doctor_pre_summary_returns_review_attribution() -> None:
    reviewed_at = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    intake_facade = StubIntakeFacade()
    intake_facade.pre_summary = PreSummaryView(
        pre_summary_id=101,
        intake_id=42,
        structured_fields={"chief_complaints": ["headache"]},
        structuring_confidence=0.88,
        low_confidence=False,
        review_state="final",
        patient_edits=None,
        doctor_corrections={"duration": "3 days"},
        review_attribution="doctor",
        reviewed_by=_PARTNER_ID,
        reviewed_at=reviewed_at,
        created_at=reviewed_at,
        updated_at=reviewed_at,
    )
    client = _client(intake_facade)

    response = client.get(
        "/v1/intake/42/pre-summary/review",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_state"] == "final"
    assert body["low_confidence"] is False
    assert body["structuring_confidence"] == 0.88
    assert body["review_attribution"] == "doctor"
    assert body["reviewed_by"] == _PARTNER_ID


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_doctor_pre_summary_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get("/v1/intake/42/pre-summary/review")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_doctor_pre_summary_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get(
        "/v1/intake/42/pre-summary/review",
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_doctor_pre_summary_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.get(
        "/v1/intake/42/pre-summary/review",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_doctor_pre_summary_unassigned_doctor_answers_404_envelope() -> None:
    intake_facade = StubIntakeFacade()
    intake_facade.error = IntakeNotFoundError(
        "pre-summary not found for intake 42 assigned to doctor 12"
    )
    client = _client(intake_facade)

    response = client.get(
        "/v1/intake/42/pre-summary/review",
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_doctor_pre_summary_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/intake/{intake_id}/pre-summary/review" in app.openapi()["paths"]
