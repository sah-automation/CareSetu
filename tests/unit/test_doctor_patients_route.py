"""PHASE-8.2 T01: GET /v1/doctor/patients doctor route (ticket #539).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner and any not-yet-``Active`` partner, call the doctor
console facade's ``list_doctor_patients``, answer the typed Patients list
shape. The facade is stubbed here - the DB-backed derivation is the facade
suite's job. Every expected failure answers the shared error envelope
(api-standards S2). Doctor RBAC is partner scope + ``partner_type ==
"doctor"`` + ``Active``: unauthenticated (401), patient (403), and non-doctor
partner scopes (403) are rejected at the edge.
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
from modules.doctor.doctor_models import DoctorPatientRow, PatientsListView
from modules.iam.domain.jwt import issue_token
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-patients-route-signing-key"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_PATIENTS_VIEW = PatientsListView(
    items=[
        DoctorPatientRow(
            patient_id=10,
            name="Ravi Kumar",
            age=32,
            has_photo=True,
            bucket="current",
            granted_scopes=["full_record", "health_background"],
            latest_case_stage="pre_summary",
        ),
        DoctorPatientRow(
            patient_id=20,
            name=None,
            age=None,
            has_photo=False,
            bucket="past",
            granted_scopes=[],
            latest_case_stage="closed",
        ),
    ],
    total=64,
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
    """Minimal doctor console stand-in recording calls and replaying a canned list."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []
        self.result: PatientsListView = _PATIENTS_VIEW

    async def list_doctor_patients(self, **kwargs: object) -> PatientsListView:
        self.called_with.append(dict(kwargs))
        return self.result


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
# Happy path
# ---------------------------------------------------------------------------


def test_patients_returns_derived_bucketed_rows() -> None:
    client = _client()

    response = client.get("/v1/doctor/patients", headers=_bearer(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 64
    assert len(body["items"]) == 2
    current = body["items"][0]
    assert current["patient_id"] == 10
    assert current["bucket"] == "current"
    assert current["name"] == "Ravi Kumar"
    assert current["age"] == 32
    assert current["has_photo"] is True
    # The raw private storage key never leaves the backend.
    assert "photo_ref" not in current
    assert current["granted_scopes"] == ["full_record", "health_background"]
    assert current["latest_case_stage"] == "pre_summary"
    past = body["items"][1]
    assert past["patient_id"] == 20
    assert past["bucket"] == "past"
    assert past["name"] is None
    assert past["granted_scopes"] == []
    assert past["latest_case_stage"] == "closed"


def test_patients_forwards_search_query() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)

    response = client.get(
        "/v1/doctor/patients?search=ravi",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert doctor_facade.called_with == [
        {"doctor_id": _PARTNER_ID, "search": "ravi", "page": 1, "per_page": 25}
    ]


def test_patients_passes_none_search_when_omitted() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)

    response = client.get("/v1/doctor/patients", headers=_bearer(_token()))

    assert response.status_code == 200
    assert doctor_facade.called_with == [
        {"doctor_id": _PARTNER_ID, "search": None, "page": 1, "per_page": 25}
    ]


def test_patients_forwards_page_and_per_page() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)

    response = client.get(
        "/v1/doctor/patients?page=3&per_page=50",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert doctor_facade.called_with == [
        {"doctor_id": _PARTNER_ID, "search": None, "page": 3, "per_page": 50}
    ]


def test_patients_rejects_per_page_over_max() -> None:
    client = _client()

    response = client.get(
        "/v1/doctor/patients?per_page=500",
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_patients_rejects_search_over_max_length() -> None:
    client = _client()

    response = client.get(
        f"/v1/doctor/patients?search={'r' * 121}",
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_patients_accepts_search_at_max_length() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)
    needle = "r" * 120

    response = client.get(
        f"/v1/doctor/patients?search={needle}",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert doctor_facade.called_with == [
        {"doctor_id": _PARTNER_ID, "search": needle, "page": 1, "per_page": 25}
    ]


def test_patients_empty_list_when_no_rows() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    doctor_facade.result = PatientsListView(items=[], total=0)
    client = _client(doctor_facade)

    response = client.get("/v1/doctor/patients", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_patients_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get("/v1/doctor/patients")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_patients_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.get("/v1/doctor/patients", headers=_bearer(_token(scope="patient")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_patients_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.get("/v1/doctor/patients", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_patients_inactive_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(status="PendingApproval")
    client = _client(partner_facade=partner_facade)

    response = client.get("/v1/doctor/patients", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_patients_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/doctor/patients" in app.openapi()["paths"]
