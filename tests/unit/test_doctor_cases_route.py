"""GET /v1/doctor/cases doctor route (ticket #647, FEAT-008).

The route is a thin adapter: resolve the partner principal through the same
helper the patients routes use, refuse any non-doctor partner and any
not-yet-``Active`` partner, call the doctor console facade's
``list_doctor_cases``, answer the typed cases-list shape. The facade is stubbed
here - the DB-backed derivation is the facade suite's job (#646). Every expected
failure answers the shared error envelope (api-standards S2). Doctor RBAC is
partner scope + ``partner_type == "doctor"`` + ``Active``: unauthenticated
(401), patient (403), and non-doctor partner scopes (403) are rejected at the
edge.

The identity forwarded to the facade is the partner profile id
(``_require_doctor``'s return), not the JWT subject id. They are different
numbers, and passing the subject id would ask the facade about a doctor that
does not exist - an empty list instead of a read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.trace import TraceMiddleware
from app.main import create_app
from modules.doctor.doctor_models import DoctorCaseRow, DoctorCasesListView
from modules.iam.domain.jwt import issue_token
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-cases-route-signing-key"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_CREATED_AT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
_UPDATED_AT = _CREATED_AT + timedelta(hours=3)

_CASES_VIEW = DoctorCasesListView(
    items=[
        DoctorCaseRow(
            case_id=501,
            stage="pre_summary",
            forced_review=True,
            created_at=_CREATED_AT,
            updated_at=_UPDATED_AT,
            patient_id=10,
            patient_name="Ravi Kumar",
            patient_age=32,
            has_photo=True,
        ),
        DoctorCaseRow(
            case_id=502,
            stage="prescription_pending",
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
            patient_id=20,
        ),
    ]
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
        self.result: DoctorCasesListView = _CASES_VIEW

    async def list_doctor_cases(self, **kwargs: object) -> DoctorCasesListView:
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


def test_cases_serves_the_facade_row_shape_unchanged() -> None:
    client = _client()

    response = client.get("/v1/doctor/cases", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _CASES_VIEW.model_dump(mode="json")


def test_cases_row_carries_patient_identity_and_case_facts() -> None:
    client = _client()

    body = client.get("/v1/doctor/cases", headers=_bearer(_token())).json()

    assert len(body["items"]) == 2
    first = body["items"][0]
    assert first["case_id"] == 501
    assert first["patient_id"] == 10
    assert first["patient_name"] == "Ravi Kumar"
    assert first["patient_age"] == 32
    assert first["stage"] == "pre_summary"
    assert first["forced_review"] is True
    assert first["has_photo"] is True
    # The second row is handed back unresolved, so the identity fields carry
    # their declared null/empty defaults and the row itself survives - the
    # degrade behaviour itself is the facade suite's to prove (#646).
    second = body["items"][1]
    assert second["patient_id"] == 20
    assert second["patient_name"] is None
    assert second["patient_age"] is None
    assert second["has_photo"] is False
    assert second["forced_review"] is False


def test_cases_forwards_the_partner_profile_id_as_the_doctor_id() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)

    response = client.get("/v1/doctor/cases", headers=_bearer(_token()))

    assert response.status_code == 200
    # The partner profile id, not the JWT subject id the tokens above carry.
    assert doctor_facade.called_with == [{"doctor_id": _PARTNER_ID}]


def test_cases_declares_no_query_parameters_in_the_served_schema() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    operation = app.openapi()["paths"]["/v1/doctor/cases"]["get"]

    assert "parameters" not in operation


def test_cases_empty_list_when_no_open_cases() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    doctor_facade.result = DoctorCasesListView(items=[])
    client = _client(doctor_facade)

    response = client.get("/v1/doctor/cases", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == {"items": []}


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_cases_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get("/v1/doctor/cases")

    assert response.status_code == 401
    envelope = response.json()
    assert envelope["code"] == "AUTH_UNAUTHENTICATED"
    # The shared envelope every gateway rejection answers (api-standards §2).
    assert set(envelope) == {"code", "message", "trace_id", "details"}


def test_cases_patient_scope_rejected_with_403() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(doctor_facade=doctor_facade)

    response = client.get("/v1/doctor/cases", headers=_bearer(_token(scope="patient")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert doctor_facade.called_with == []


def test_cases_non_doctor_partner_rejected_with_403() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(
        doctor_facade=doctor_facade, partner_facade=StubPartnerFacade(partner_type="lab")
    )

    response = client.get("/v1/doctor/cases", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert doctor_facade.called_with == []


def test_cases_inactive_partner_rejected_with_403() -> None:
    doctor_facade = StubDoctorConsoleFacade()
    client = _client(
        doctor_facade=doctor_facade, partner_facade=StubPartnerFacade(status="PendingApproval")
    )

    response = client.get("/v1/doctor/cases", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert doctor_facade.called_with == []


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_cases_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/doctor/cases" in app.openapi()["paths"]


def test_cases_response_model_is_published_in_the_served_schema() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    schema = app.openapi()
    operation = schema["paths"]["/v1/doctor/cases"]["get"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/DoctorCasesListView")
    assert "DoctorCaseRow" in schema["components"]["schemas"]
