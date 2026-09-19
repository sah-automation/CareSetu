"""PHASE-8.1 T09: GET /v1/intake/pre-summary/{pre_summary_id}/detail doctor route (#484).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner, call the intake facade's ``get_doctor_intake_detail``,
answer the typed intake-detail shape (transcript + media refs). Both facades
are stubbed here - the DB-backed content and assignment-scoping behavior is
the facade suite's job. Every expected failure answers the shared error
envelope (api-standards S2). Doctor RBAC is partner scope +
``partner_type == "doctor"``: unauthenticated (401), patient (403), and
non-doctor partner scopes (403) are rejected at the edge; an unassigned
doctor surfaces the intake 404 (the facade never reveals an intake assigned
to another doctor).
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
from modules.intake.intake_models import IntakeDetailView, MediaRefView
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-intake-detail-route-signing-key"

_TRACE_ID = "unit-trace-doctor-intake-detail-9101"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_INTAKE_DETAIL = IntakeDetailView(
    intake_id=42,
    patient_id=7,
    mode="voice",
    language="hi",
    status="presummarized",
    record_attempts=2,
    text=None,
    transcript="मुझे लगातार सिरदर्द रहता है और मतली होती है।",
    transcript_usability="ok",
    forced_text=False,
    media_refs=[
        MediaRefView(
            media_ref_id=301,
            media_type="audio/mpeg",
            object_key="in/42/301.mp3",
            audio_duration_ms=28400,
            file_size_bytes=221_440,
            record_attempt=1,
        ),
        MediaRefView(
            media_ref_id=302,
            media_type="audio/mpeg",
            object_key="in/42/302.mp3",
            audio_duration_ms=17090,
            file_size_bytes=132_096,
            record_attempt=2,
        ),
    ],
    created_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
    updated_at=datetime(2026, 9, 15, 11, 0, tzinfo=UTC),
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
        self.detail: IntakeDetailView = _INTAKE_DETAIL
        self.error: Exception | None = None

    async def get_doctor_intake_detail(self, **kwargs: object) -> IntakeDetailView:
        self.called_with.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.detail


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


def _url(pre_summary_id: int = 101) -> str:
    return f"/v1/intake/pre-summary/{pre_summary_id}/detail"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_doctor_intake_detail_returns_transcript_and_media_refs() -> None:
    intake_facade = StubIntakeFacade()
    client = _client(intake_facade)

    response = client.get(_url(), headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID})

    assert response.status_code == 200
    assert intake_facade.called_with == [{"pre_summary_id": 101, "doctor_id": _PARTNER_ID}]
    body = response.json()
    assert body["intake_id"] == 42
    assert body["patient_id"] == 7
    assert body["mode"] == "voice"
    assert body["language"] == "hi"
    assert body["transcript"] == _INTAKE_DETAIL.transcript
    assert body["transcript_usability"] == "ok"
    assert len(body["media_refs"]) == 2
    assert body["media_refs"][1]["media_ref_id"] == 302
    assert body["media_refs"][1]["record_attempt"] == 2
    assert body["media_refs"][1]["audio_duration_ms"] == 17090


def test_doctor_intake_detail_returns_forced_text_clip() -> None:
    intake_facade = StubIntakeFacade()
    recorded: dict[str, object] = dict(_INTAKE_DETAIL.model_dump())
    recorded["transcript"] = None
    recorded["transcript_usability"] = None
    recorded["forced_text"] = True
    recorded["text"] = "बुखार और खांसी है।"
    recorded["media_refs"] = []
    intake_facade.detail = IntakeDetailView.model_validate(recorded)
    client = _client(intake_facade)

    response = client.get(_url(), headers=_bearer(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] is None
    assert body["forced_text"] is True
    assert body["text"] == "बुखार और खांसी है।"
    assert body["media_refs"] == []


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_doctor_intake_detail_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get(_url())

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_doctor_intake_detail_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get(_url(), headers=_bearer(_token(scope="patient")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_doctor_intake_detail_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.get(_url(), headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_doctor_intake_detail_unassigned_doctor_answers_404_envelope() -> None:
    intake_facade = StubIntakeFacade()
    intake_facade.error = IntakeNotFoundError(
        "intake detail not found for pre-summary 101 assigned to doctor 12"
    )
    client = _client(intake_facade)

    response = client.get(_url(), headers=_bearer(_token()) | {"X-Request-Id": _TRACE_ID})

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_doctor_intake_detail_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/intake/pre-summary/{pre_summary_id}/detail" in app.openapi()["paths"]
