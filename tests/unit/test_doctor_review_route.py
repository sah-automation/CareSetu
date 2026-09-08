"""PHASE-7 T13: POST /v1/intake/{intake_id}/review doctor route (ticket #357).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner, call the intake facade's ``mark_pre_summary_reviewed``
with the review DTO, answer the typed reviewed-result shape. Both facades are
stubbed here - the DB-backed review-and-edit behavior is the facade and
integration suites' job. Every expected failure answers the shared error
envelope (api-standards S2). Doctor RBAC is partner scope +
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
from modules.intake.domain.exceptions import (
    IllegalPreSummaryTransitionError,
    IntakeNotFoundError,
)
from modules.intake.intake_models import PreSummaryReviewResult
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-review-route-signing-key"

_TRACE_ID = "unit-trace-doctor-review-9000"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_REVIEW_RESULT = PreSummaryReviewResult(
    intake_id=42,
    pre_summary_id=101,
    review_state="reviewed",
    reviewed_copy={"chief_complaints": ["headache"], "duration": "3 days"},
    changed_fields=["duration"],
    review_attribution="doctor",
    reviewed_by=_PARTNER_ID,
    reviewed_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
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
        self.review_result: PreSummaryReviewResult = _REVIEW_RESULT
        self.error: Exception | None = None

    async def mark_pre_summary_reviewed(self, **kwargs: object) -> PreSummaryReviewResult:
        self.called_with.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.review_result


class StubPartnerFacade:
    """Minimal partner facade stand-in resolving the caller's partner profile."""

    def __init__(self, partner_type: str = "doctor") -> None:
        self.partner_type = partner_type
        self.called_with: list[dict] = []

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        self.called_with.append({"identity_id": identity_id})
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


def test_review_forwards_corrections_to_facade_and_returns_result() -> None:
    intake_facade = StubIntakeFacade()
    partner_facade = StubPartnerFacade()
    client = _client(intake_facade, partner_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _REVIEW_RESULT.model_dump(mode="json")
    assert partner_facade.called_with == [{"identity_id": _DOCTOR_IDENTITY}]
    assert intake_facade.called_with == [
        {"intake_id": 42, "doctor_id": _PARTNER_ID, "corrections": {"duration": "3 days"}}
    ]


def test_review_without_corrections_forwards_none() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert intake_facade.called_with[0]["corrections"] is None


def test_review_unauthenticated_rejected_with_401() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"
    assert intake_facade.called_with == []


def test_review_patient_scope_rejected_with_403() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert intake_facade.called_with == []


def test_review_non_doctor_partner_rejected_with_403() -> None:
    intake_facade = StubIntakeFacade()
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(intake_facade, partner_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert intake_facade.called_with == []


def test_review_malformed_corrections_rejected_at_the_gateway_with_envelope() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": "not-a-mapping"},
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == _TRACE_ID
    assert intake_facade.called_with == []


def test_review_unknown_field_rejected_at_the_gateway() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}, "invite_code": "x"},
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert intake_facade.called_with == []


def test_review_missing_intake_answers_404_envelope() -> None:
    intake_facade = StubIntakeFacade()
    intake_facade.error = IntakeNotFoundError("pre-summary not found for intake 42")
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


def test_review_illegal_pre_summary_transition_answers_422_envelope() -> None:
    intake_facade = StubIntakeFacade()
    intake_facade.error = IllegalPreSummaryTransitionError()
    client = _client(intake_facade)

    response = client.post(
        "/v1/intake/42/review",
        json={"corrections": {"duration": "3 days"}},
        headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "ILLEGAL_PRE_SUMMARY_TRANSITION"
    assert body["trace_id"] == _TRACE_ID


def test_review_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/intake/{intake_id}/review" in app.openapi()["paths"]
