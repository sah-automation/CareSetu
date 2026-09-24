"""PHASE-8.2 T02: doctor patient detail + photo routes (ticket #540).

The routes are thin adapters over the doctor console facade: the detail
answers the section-gated typed shape and the photo endpoint streams the
gated bytes. The facade is stubbed here - the DB-backed gating is the facade
suite's job. Denials render as (a) locked ``null`` sections (never an error)
in the detail, and (b) a ``403 RECORD_ACCESS_DENIED`` envelope for a direct
photo fetch without a grant. Doctor RBAC matches the Patients list route:
partner scope + ``partner_type == "doctor"`` + ``Active``.
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
from modules.doctor.doctor_models import (
    CaseWorkspaceLink,
    ContactSection,
    DoctorPatientDetailView,
    PatientsListView,
)
from modules.health.facade import RecordAccessDeniedError
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import PhotoContent
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-patient-detail-route-signing-key"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30
_PATIENT_ID = 10

_PHOTO = PhotoContent(data=b"\xff\xd8jpeg", media_type="image/jpeg")

_DETAIL_VIEW = DoctorPatientDetailView(
    patient_id=_PATIENT_ID,
    bucket="current",
    granted_scopes=["full_record", "health_background"],
    latest_case_stage="pre_summary",
    case_workspace=CaseWorkspaceLink(case_id=7, stage="pre_summary"),
    contact=ContactSection(
        name="Ravi Kumar",
        age=32,
        gender="male",
        area="Bengaluru",
        emergency_contact="9876543210",
        photo_ref="profiles/abc",
    ),
    consultation_history=None,
    health_background=None,
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


class StubDoctorConsoleFacade:
    """Minimal doctor console stand-in replaying canned detail/photo answers."""

    def __init__(self) -> None:
        self.detail_result: DoctorPatientDetailView = _DETAIL_VIEW
        self.photo_result: PhotoContent | None = _PHOTO
        self.photo_error: Exception | None = None
        self.detail_calls: list[dict] = []
        self.photo_calls: list[dict] = []

    async def get_doctor_patient_detail(self, **kwargs: object) -> DoctorPatientDetailView:
        self.detail_calls.append(dict(kwargs))
        return self.detail_result

    async def get_doctor_patient_photo(self, **kwargs: object) -> PhotoContent | None:
        self.photo_calls.append(dict(kwargs))
        if self.photo_error is not None:
            raise self.photo_error
        return self.photo_result

    async def list_doctor_patients(self, **kwargs: object) -> PatientsListView:
        return PatientsListView(items=[], total=0)


class StubPartnerFacade:
    """Minimal partner facade stand-in resolving the caller's partner profile."""

    def __init__(self, partner_type: str = "doctor", status: str = "Active") -> None:
        self.partner_type = partner_type
        self.status = status

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        return PartnerView(
            partner_id=_PARTNER_ID,
            partner_type=self.partner_type,
            status=self.status,
            round=2,
        )


def _client(
    doctor_facade: StubDoctorConsoleFacade | None = None,
    partner_facade: StubPartnerFacade | None = None,
) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.doctor_console_facade = (
        doctor_facade if doctor_facade is not None else StubDoctorConsoleFacade()
    )
    app.state.partner_facade = partner_facade if partner_facade is not None else StubPartnerFacade()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Detail happy path
# ---------------------------------------------------------------------------


def test_detail_returns_section_gated_view() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade)

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}", headers=_bearer(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == _PATIENT_ID
    assert body["bucket"] == "current"
    assert body["granted_scopes"] == ["full_record", "health_background"]
    assert body["latest_case_stage"] == "pre_summary"
    assert body["case_workspace"] == {"case_id": 7, "stage": "pre_summary"}
    assert body["contact"] == {
        "name": "Ravi Kumar",
        "age": 32,
        "gender": "male",
        "area": "Bengaluru",
        "emergency_contact": "9876543210",
        "photo_ref": "profiles/abc",
    }
    assert body["consultation_history"] is None
    assert body["health_background"] is None
    assert doctor_facade.detail_calls == [{"doctor_id": _PARTNER_ID, "patient_id": _PATIENT_ID}]


def test_detail_locked_sections_serialize_as_null() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    doctor_facade.detail_result = DoctorPatientDetailView(
        patient_id=_PATIENT_ID,
        bucket="past",
        granted_scopes=[],
        latest_case_stage="closed",
        case_workspace=None,
        contact=None,
        consultation_history=None,
        health_background=None,
    )
    client = _client(doctor_facade)

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}", headers=_bearer(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["contact"] is None
    assert body["consultation_history"] is None
    assert body["health_background"] is None
    assert body["case_workspace"] is None


# ---------------------------------------------------------------------------
# Photo happy path
# ---------------------------------------------------------------------------


def test_photo_streams_gated_bytes() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade)

    response = client.get(
        f"/v1/doctor/patients/{_PATIENT_ID}/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.content == b"\xff\xd8jpeg"
    assert response.headers["content-type"] == "image/jpeg"
    assert doctor_facade.photo_calls == [{"doctor_id": _PARTNER_ID, "patient_id": _PATIENT_ID}]


def test_photo_without_stored_photo_answers_shared_404() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    doctor_facade.photo_result = None
    client = _client(doctor_facade)

    response = client.get(
        f"/v1/doctor/patients/{_PATIENT_ID}/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "PROFILE_PHOTO_NOT_FOUND"


def test_photo_without_live_grant_fails_closed_with_403() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    doctor_facade.photo_error = RecordAccessDeniedError("no live consent grant for this patient")
    client = _client(doctor_facade)

    response = client.get(
        f"/v1/doctor/patients/{_PATIENT_ID}/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "RECORD_ACCESS_DENIED"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_detail_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_detail_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get(
        f"/v1/doctor/patients/{_PATIENT_ID}",
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_detail_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_detail_inactive_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(status="PendingApproval")
    client = _client(partner_facade=partner_facade)

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_photo_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get(f"/v1/doctor/patients/{_PATIENT_ID}/photo")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_photo_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get(
        f"/v1/doctor/patients/{_PATIENT_ID}/photo",
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_detail_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert f"/v1/doctor/patients/{_PATIENT_ID}" not in app.openapi()["paths"]
    assert "/v1/doctor/patients/{patient_id}" in app.openapi()["paths"]
    assert "/v1/doctor/patients/{patient_id}/photo" in app.openapi()["paths"]


def test_list_route_still_served_after_detail_addition() -> None:
    client = _client()

    response = client.get(
        "/v1/doctor/patients",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
