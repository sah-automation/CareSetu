"""PHASE-8 T06: doctor care routes & RBAC (ticket #422).

Thin adapters: parse the typed request, call the care facade, answer the
typed result. The facade is stubbed here - the DB-backed behavior is the
integration suite's job. Every expected failure answers the shared error
envelope (api-standards §2). Doctor RBAC (``require_partner`` + resolved
partner profile) rejects unauthenticated callers (401) and refuses
non-doctor / non-active partner profiles (403).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.care.care_models import (
    CaseDetailView,
    DoctorInputResult,
    PrescriptionDetailView,
    RxItemView,
)
from modules.care.domain.exceptions import (
    CareNotFoundError,
    CareValidationError,
    IllegalCareTransitionError,
    IllegalPrescriptionTransitionError,
)
from modules.iam.domain.jwt import issue_token
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-care-route-signing-key"


def _token(*, subject_id: int = 1, scope: str = "partner") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(
    facade: StubCareFacade | None = None,
    partner: PartnerView | None = None,
) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.care_facade = facade if facade is not None else StubCareFacade()
    app.state.partner_facade = StubPartnerFacade(
        partner if partner is not None else _DOCTOR_PARTNER
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Stubbed facades
# ---------------------------------------------------------------------------

_T = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

_DOCTOR_PARTNER = PartnerView(partner_id=5, partner_type="doctor", status="Active", round=1)
_LAB_PARTNER = PartnerView(partner_id=5, partner_type="lab", status="Active", round=1)
_REGISTERED_DOCTOR = PartnerView(partner_id=5, partner_type="doctor", status="Registered", round=0)

_CASE_VIEW = CaseDetailView(
    case_id=42,
    patient_id=7,
    doctor_id=5,
    pre_summary_id=101,
    stage="prescription_pending",
    closed_at=None,
    close_reason=None,
    created_at=_T,
    updated_at=_T,
)

_OPEN_CASES = [
    CaseDetailView(
        case_id=1,
        patient_id=7,
        doctor_id=5,
        pre_summary_id=90,
        stage="pre_summary",
        closed_at=None,
        close_reason=None,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    ),
    CaseDetailView(
        case_id=2,
        patient_id=8,
        doctor_id=5,
        pre_summary_id=91,
        stage="prescription_pending",
        closed_at=None,
        close_reason=None,
        created_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    ),
]

_DOCTOR_INPUT_RESULT = DoctorInputResult(
    input_id=201,
    case_id=42,
    input_type="voice",
    media_ref="care/case-42/voice-1.webm",
    sensitive_class="normal",
)

_RX_DRAFT_VIEW = PrescriptionDetailView(
    prescription_id=301,
    case_id=42,
    status="draft",
    source="ai_draft",
    attempt_no=1,
    draft_snapshot={"rx_items": [{"name": "Paracetamol", "dose": "500mg", "duration": "5 days"}]},
    issued_at=None,
    attributed_doctor=None,
    items=[],
    created_at=_T,
    updated_at=_T,
)

_RX_ISSUED_VIEW = PrescriptionDetailView(
    prescription_id=301,
    case_id=42,
    status="issued",
    source="ai_draft",
    attempt_no=1,
    draft_snapshot={},
    issued_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    attributed_doctor=5,
    items=[
        RxItemView(
            rx_item_id=1,
            prescription_id=301,
            sequence=1,
            name="Paracetamol",
            dose="500mg",
            duration="5 days",
        )
    ],
    created_at=_T,
    updated_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
)


class StubCareFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.called_with: list[tuple[str, dict]] = []
        self.case_view: CaseDetailView = _CASE_VIEW
        self.open_cases: list[CaseDetailView] = _OPEN_CASES
        self.doctor_input_result: DoctorInputResult = _DOCTOR_INPUT_RESULT
        self.rx_draft_view: PrescriptionDetailView = _RX_DRAFT_VIEW
        self.rx_issued_view: PrescriptionDetailView = _RX_ISSUED_VIEW
        self.error: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def mark_consult_complete(self, **kwargs: object) -> CaseDetailView:
        self.called_with.append(("mark_consult_complete", dict(kwargs)))
        self._maybe_raise()
        return self.case_view

    async def list_doctor_cases(self, **kwargs: object) -> list[CaseDetailView]:
        self.called_with.append(("list_doctor_cases", dict(kwargs)))
        self._maybe_raise()
        return self.open_cases

    async def get_case(self, **kwargs: object) -> CaseDetailView:
        self.called_with.append(("get_case", dict(kwargs)))
        self._maybe_raise()
        return self.case_view

    async def submit_doctor_input(self, **kwargs: object) -> DoctorInputResult:
        self.called_with.append(("submit_doctor_input", dict(kwargs)))
        self._maybe_raise()
        return self.doctor_input_result

    async def create_rx_draft(self, **kwargs: object) -> PrescriptionDetailView:
        self.called_with.append(("create_rx_draft", dict(kwargs)))
        self._maybe_raise()
        return self.rx_draft_view

    async def save_rx_revision(self, **kwargs: object) -> PrescriptionDetailView:
        self.called_with.append(("save_rx_revision", dict(kwargs)))
        self._maybe_raise()
        return self.rx_draft_view

    async def approve_prescription(self, **kwargs: object) -> PrescriptionDetailView:
        self.called_with.append(("approve_prescription", dict(kwargs)))
        self._maybe_raise()
        return self.rx_issued_view

    async def reject_prescription(self, **kwargs: object) -> PrescriptionDetailView:
        self.called_with.append(("reject_prescription", dict(kwargs)))
        self._maybe_raise()
        return self.rx_draft_view

    async def get_approved_prescription(self, **kwargs: object) -> PrescriptionDetailView:
        self.called_with.append(("get_approved_prescription", dict(kwargs)))
        self._maybe_raise()
        return self.rx_issued_view


class StubPartnerFacade:
    """Minimal partner facade stand-in: resolve_partner replays one profile."""

    def __init__(self, partner: PartnerView) -> None:
        self.partner = partner
        self.resolve_calls: list[int] = []

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        self.resolve_calls.append(identity_id)
        return self.partner


# ---------------------------------------------------------------------------
# RBAC skin
# ---------------------------------------------------------------------------


def test_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.post("/v1/care/cases/42/consult-complete")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/consult-complete",
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_non_doctor_partner_rejected_with_403() -> None:
    facade = StubCareFacade()
    client = _client(facade, partner=_LAB_PARTNER)

    response = client.post(
        "/v1/care/cases/42/consult-complete",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert client.app.state.partner_facade.resolve_calls == [1]
    assert facade.called_with == []


def test_non_active_doctor_rejected_with_403() -> None:
    client = _client(partner=_REGISTERED_DOCTOR)

    response = client.post(
        "/v1/care/cases/42/consult-complete",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert client.app.state.partner_facade.resolve_calls == [1]


# ---------------------------------------------------------------------------
# Tests: mark_consult_complete
# ---------------------------------------------------------------------------


def test_consult_complete_returns_case_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/consult-complete",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _CASE_VIEW.model_dump(mode="json")
    assert facade.called_with == [("mark_consult_complete", {"doctor_id": 5, "case_id": 42})]


def test_consult_complete_illegal_transition_envelope() -> None:
    facade = StubCareFacade()
    facade.error = IllegalCareTransitionError("MARK_CONSULT_COMPLETE is illegal while pre_summary")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/consult-complete",
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "ILLEGAL_CARE_TRANSITION"


def test_consult_complete_not_found_envelope() -> None:
    facade = StubCareFacade()
    facade.error = CareNotFoundError("case 99 not found for doctor 5")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/99/consult-complete",
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CARE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: list_open_cases
# ---------------------------------------------------------------------------


def test_list_cases_returns_open_case_views() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.get("/v1/care/cases", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == [case.model_dump(mode="json") for case in _OPEN_CASES]
    assert facade.called_with == [("list_doctor_cases", {"doctor_id": 5})]


def test_list_cases_unauthenticated_rejected() -> None:
    client = _client()

    response = client.get("/v1/care/cases")

    assert response.status_code == 401


def test_list_cases_non_doctor_rejected() -> None:
    client = _client(partner=_LAB_PARTNER)

    response = client.get("/v1/care/cases", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


# ---------------------------------------------------------------------------
# Tests: get_case
# ---------------------------------------------------------------------------


def test_get_case_returns_case_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.get("/v1/care/cases/42", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _CASE_VIEW.model_dump(mode="json")
    assert facade.called_with == [("get_case", {"doctor_id": 5, "case_id": 42})]


def test_get_case_not_found_envelope() -> None:
    facade = StubCareFacade()
    facade.error = CareNotFoundError("case 99 not found for doctor 5")
    client = _client(facade)

    response = client.get("/v1/care/cases/99", headers=_bearer(_token()))

    assert response.status_code == 404
    assert response.json()["code"] == "CARE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: submit_doctor_input
# ---------------------------------------------------------------------------


def test_doctor_input_returns_result() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/doctor-input",
        json={
            "input_type": "voice",
            "media_ref": "care/case-42/voice-1.webm",
            "sensitive_class": "normal",
        },
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _DOCTOR_INPUT_RESULT.model_dump(mode="json")
    assert facade.called_with == [
        (
            "submit_doctor_input",
            {
                "doctor_id": 5,
                "case_id": 42,
                "input_type": "voice",
                "media_ref": "care/case-42/voice-1.webm",
                "sensitive_class": "normal",
            },
        )
    ]


def test_doctor_input_without_sensitive_class_defaults_none() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/doctor-input",
        json={"input_type": "voice", "media_ref": "care/case-42/voice-1.webm"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.called_with[0][1]["sensitive_class"] is None


def test_doctor_input_invalid_input_type_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/doctor-input",
        json={"input_type": "video", "media_ref": "care/case-42/voice-1.webm"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_doctor_input_unknown_field_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/doctor-input",
        json={
            "input_type": "voice",
            "media_ref": "care/case-42/voice-1.webm",
            "extra": "bad",
        },
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_doctor_input_closed_case_envelope() -> None:
    facade = StubCareFacade()
    facade.error = CareValidationError("submit_doctor_input is illegal while the case is closed")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/doctor-input",
        json={"input_type": "photo", "media_ref": "care/case-42/photo-1.jpg"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "CARE_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Tests: create_rx_draft
# ---------------------------------------------------------------------------


def test_rx_draft_ai_source_returns_prescription_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/draft",
        json={"source": "ai_draft"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _RX_DRAFT_VIEW.model_dump(mode="json")
    assert facade.called_with == [
        ("create_rx_draft", {"case_id": 42, "doctor_id": 5, "source": "ai_draft", "items": None})
    ]


def test_rx_draft_manual_forwards_items() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/draft",
        json={"source": "manual", "items": [{"name": "Paracetamol", "dose": "500mg"}]},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    items = facade.called_with[0][1]["items"]
    assert len(items) == 1
    assert items[0].name == "Paracetamol"
    assert items[0].dose == "500mg"
    assert items[0].duration is None


def test_rx_draft_invalid_source_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/rx/draft",
        json={"source": "email"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_rx_draft_drafting_cap_envelope() -> None:
    facade = StubCareFacade()
    facade.error = IllegalPrescriptionTransitionError("CREATE_DRAFT is illegal: drafting cap met")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/draft",
        json={"source": "ai_draft"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ILLEGAL_PRESCRIPTION_TRANSITION"


# ---------------------------------------------------------------------------
# Tests: save_rx_revision
# ---------------------------------------------------------------------------


def test_revision_returns_prescription_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/revision",
        json={"rx_items": [{"name": "Paracetamol", "dose": "500mg", "duration": "5 days"}]},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _RX_DRAFT_VIEW.model_dump(mode="json")
    call_kwargs = facade.called_with[0][1]
    assert call_kwargs["case_id"] == 42
    assert call_kwargs["rx_id"] == 301
    assert call_kwargs["doctor_id"] == 5
    assert call_kwargs["rx_items"][0].name == "Paracetamol"


def test_revision_unknown_field_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/rx/301/revision",
        json={"rx_items": [{"name": "Paracetamol"}], "extra": "bad"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_revision_unauthenticated_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/care/cases/42/rx/301/revision",
        json={"rx_items": [{"name": "Paracetamol"}]},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: approve_prescription
# ---------------------------------------------------------------------------


def test_approve_returns_issued_prescription_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/approve",
        json={"verification_declaration": True},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _RX_ISSUED_VIEW.model_dump(mode="json")
    assert facade.called_with == [
        (
            "approve_prescription",
            {
                "case_id": 42,
                "rx_id": 301,
                "doctor_id": 5,
                "verification_declaration": True,
            },
        )
    ]


def test_approve_missing_declaration_envelope_via_facade() -> None:
    facade = StubCareFacade()
    facade.error = CareValidationError("approval requires verification_declaration=true")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/approve",
        json={},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "CARE_VALIDATION_ERROR"


def test_approve_not_found_envelope() -> None:
    facade = StubCareFacade()
    facade.error = CareNotFoundError("case 42 not found for doctor 5")
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/approve",
        json={"verification_declaration": True},
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CARE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: reject_prescription
# ---------------------------------------------------------------------------


def test_reject_returns_prescription_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/reject",
        json={"reason": "dose incorrect"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _RX_DRAFT_VIEW.model_dump(mode="json")
    assert facade.called_with == [
        (
            "reject_prescription",
            {
                "case_id": 42,
                "rx_id": 301,
                "doctor_id": 5,
                "reason": "dose incorrect",
            },
        )
    ]


def test_reject_empty_reason_left_to_machine() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.post(
        "/v1/care/cases/42/rx/301/reject",
        json={"reason": ""},
        headers=_bearer(_token()),
    )

    # The empty-reason gate is machine-enforced in the prescription state
    # machine; the thin route forwards to the facade untouched.
    assert response.status_code == 200
    assert facade.called_with[0][1]["reason"] == ""


# ---------------------------------------------------------------------------
# Tests: get_approved_prescription
# ---------------------------------------------------------------------------


def test_get_approved_prescription_returns_view() -> None:
    facade = StubCareFacade()
    client = _client(facade)

    response = client.get("/v1/care/prescriptions/301", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _RX_ISSUED_VIEW.model_dump(mode="json")
    assert facade.called_with == [("get_approved_prescription", {"rx_id": 301})]


def test_get_approved_prescription_not_found_envelope() -> None:
    facade = StubCareFacade()
    facade.error = CareNotFoundError("approved prescription 999 not found")
    client = _client(facade)

    response = client.get("/v1/care/prescriptions/999", headers=_bearer(_token()))

    assert response.status_code == 404
    assert response.json()["code"] == "CARE_NOT_FOUND"


def test_get_approved_prescription_unauthenticated_rejected() -> None:
    client = _client()

    response = client.get("/v1/care/prescriptions/301")

    assert response.status_code == 401


def test_get_approved_prescription_non_doctor_rejected() -> None:
    client = _client(partner=_LAB_PARTNER)

    response = client.get("/v1/care/prescriptions/301", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
