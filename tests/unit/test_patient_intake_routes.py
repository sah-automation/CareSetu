"""PHASE-7 T12: patient intake HTTP routes (ticket #356).

Thin adapters: parse the typed request, call the intake facade, answer the
typed result. The facade is stubbed here - the DB-backed behavior is the
integration suite's job. Every expected failure answers the shared error
envelope (api-standards S2). Patient RBAC (``require_patient``) rejects
unauthenticated callers (401) and partner/doctor-scope callers (403).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.intake.domain.exceptions import (
    IllegalIntakeTransitionError,
    IntakeNotFoundError,
    IntakeValidationError,
    MediaTransferError,
)
from modules.intake.intake_models import (
    IntakeDetailView,
    IntakeSubmitResult,
    MediaUploadRef,
    PatientEditsResult,
    PreSummaryView,
    ReRecordResult,
)

_SIGNING_KEY = "test-intake-route-signing-key"


def _token(*, subject_id: int = 7, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(facade: StubIntakeFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.intake_facade = facade if facade is not None else StubIntakeFacade()
    return TestClient(app)


def _rate_limited_client(
    facade: StubIntakeFacade | None = None, *, max_requests: int = 2
) -> TestClient:
    """Like ``_client`` but with the strict-tier gateway limiter enabled.

    The intake write surface and the OTP/auth routes each keep an independent
    per-IP tier (PS-05, #403): the intake tier is exhausted by the row-writing
    trio below while auth-only limiting semantics remain untouched. Tests drive
    a small exhausted tier instead of the 10/60s production default.
    """
    settings = Settings(
        gateway_jwt_verify_enabled=True,
        gateway_jwt_signing_key=_SIGNING_KEY,
        gateway_rate_limit_enabled=True,
        gateway_rate_limit_auth_max_requests=max_requests,
        gateway_rate_limit_auth_window_seconds=60,
        gateway_rate_limit_intake_max_requests=max_requests,
        gateway_rate_limit_intake_window_seconds=60,
    )
    app = create_app(settings=settings)
    app.state.intake_facade = facade if facade is not None else StubIntakeFacade()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Stubbed facade
# ---------------------------------------------------------------------------

_SUBMIT_RESULT = IntakeSubmitResult(intake_id=42, status="captured")

_DETAIL_VIEW = IntakeDetailView(
    intake_id=42,
    patient_id=7,
    mode="text",
    language="hi",
    status="captured",
    record_attempts=1,
    text="Mujhe sar dard hai",
    transcript=None,
    transcript_usability=None,
    forced_text=False,
    media_refs=[],
    created_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    updated_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
)

_PRE_SUMMARY_VIEW = PreSummaryView(
    pre_summary_id=101,
    intake_id=42,
    structured_fields={"chief_complaints": ["headache"]},
    structuring_confidence=Decimal("0.85"),
    low_confidence=False,
    review_state="draft",
    patient_edits=None,
    doctor_corrections=None,
    review_attribution=None,
    reviewed_by=None,
    reviewed_at=None,
    created_at=datetime(2026, 9, 1, 10, 5, tzinfo=UTC),
    updated_at=datetime(2026, 9, 1, 10, 5, tzinfo=UTC),
)

_MEDIA_REF = MediaUploadRef(
    object_key="intake/patient-7/clip-abc.webm",
    media_type="audio",
    audio_duration_ms=5000,
    file_size_bytes=12000,
    record_attempt=1,
)

_RERECORD_RESULT = ReRecordResult(
    intake_id=42,
    accepted=True,
    status="structuring",
    record_attempts=2,
    forced_text=False,
    media_ref_id=55,
)

_PATIENT_EDITS_RESULT = PatientEditsResult(
    intake_id=42,
    pre_summary_id=101,
    patient_edits={"duration": "3 days, not 1 day"},
)


class StubIntakeFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.called_with: list[tuple[str, dict]] = []
        self.submit_result: IntakeSubmitResult = _SUBMIT_RESULT
        self.detail_view: IntakeDetailView = _DETAIL_VIEW
        self.pre_summary_view: PreSummaryView = _PRE_SUMMARY_VIEW
        self.media_ref: MediaUploadRef = _MEDIA_REF
        self.rerecord_result: ReRecordResult = _RERECORD_RESULT
        self.patient_edits_result: PatientEditsResult = _PATIENT_EDITS_RESULT
        self.media_bytes: bytes = b"\xff" * 16
        self.error: Exception | None = None
        self.pre_summary_error: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def submit_intake(self, **kwargs: object) -> IntakeSubmitResult:
        self.called_with.append(("submit_intake", dict(kwargs)))
        self._maybe_raise()
        return self.submit_result

    async def upload_intake_media(self, **kwargs: object) -> MediaUploadRef:
        self.called_with.append(("upload_intake_media", dict(kwargs)))
        self._maybe_raise()
        return self.media_ref

    async def re_record_intake(self, **kwargs: object) -> ReRecordResult:
        self.called_with.append(("re_record_intake", dict(kwargs)))
        self._maybe_raise()
        return self.rerecord_result

    async def get_intake(self, **kwargs: object) -> IntakeDetailView:
        self.called_with.append(("get_intake", dict(kwargs)))
        self._maybe_raise()
        return self.detail_view

    async def get_pre_summary(self, **kwargs: object) -> PreSummaryView:
        self.called_with.append(("get_pre_summary", dict(kwargs)))
        if self.pre_summary_error is not None:
            raise self.pre_summary_error
        self._maybe_raise()
        return self.pre_summary_view

    async def save_patient_pre_summary_edits(self, **kwargs: object) -> PatientEditsResult:
        self.called_with.append(("save_patient_pre_summary_edits", dict(kwargs)))
        self._maybe_raise()
        return self.patient_edits_result

    async def get_intake_media(self, **kwargs: object) -> bytes:
        self.called_with.append(("get_intake_media", dict(kwargs)))
        self._maybe_raise()
        return self.media_bytes


# ---------------------------------------------------------------------------
# Tests: submit_intake
# ---------------------------------------------------------------------------


def test_submit_text_intake_returns_result() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi", "text": "Mujhe sar dard hai"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _SUBMIT_RESULT.model_dump(mode="json")
    assert facade.called_with == [
        (
            "submit_intake",
            {
                "patient_id": 7,
                "mode": "text",
                "language": "hi",
                "text": "Mujhe sar dard hai",
                "media_ref": None,
            },
        )
    ]


def test_submit_voice_intake_forwards_media_ref() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)
    media_ref = _MEDIA_REF.model_dump(mode="json")

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "voice", "language": "en", "media_ref": media_ref},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    call_kwargs = facade.called_with[0][1]
    assert call_kwargs["mode"] == "voice"
    assert call_kwargs["language"] == "en"
    assert call_kwargs["text"] is None
    assert call_kwargs["media_ref"] is not None


def test_submit_voice_ref_with_raw_mime_media_type_rejected() -> None:
    """A crafted ref carrying the browser MIME type is a 422, never a 500.

    The DB only admits ``audio``/``photo`` (issue #375); a caller that skips
    upload and hands ``audio/webm`` straight to submit must be refused at the
    boundary instead of tripping the IntegrityError path.
    """
    client = _client()

    media_ref = {**_MEDIA_REF.model_dump(mode="json"), "media_type": "audio/webm"}
    response = client.post(
        "/v1/intake/submit",
        json={"mode": "voice", "language": "en", "media_ref": media_ref},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_submit_intake_unauthenticated_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi", "text": "test"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_submit_intake_partner_scope_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi", "text": "test"},
        headers=_bearer(_token(scope="partner")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_submit_intake_invalid_mode_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "email", "language": "hi", "text": "test"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_submit_intake_invalid_language_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "fr", "text": "test"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_submit_intake_missing_text_rejected_via_facade() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeValidationError("text mode intake requires text content")
    client = _client(facade)

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INTAKE_VALIDATION_ERROR"
    assert "requires text content" in body["message"]


def test_submit_intake_text_too_long_rejected_via_facade() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeValidationError("text exceeds 2000 character cap (2001 chars)")
    client = _client(facade)

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi", "text": "x" * 2001},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INTAKE_VALIDATION_ERROR"
    assert "2000 character cap" in body["message"]


# ---------------------------------------------------------------------------
# Tests: upload_media
# ---------------------------------------------------------------------------


def test_upload_media_returns_clip_ticket() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-media?audio_duration_ms=5000",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object_key"] == "intake/patient-7/clip-abc.webm"
    assert facade.called_with[0][0] == "upload_intake_media"
    assert facade.called_with[0][1]["patient_id"] == 7


def test_upload_media_normalises_browser_mime_to_canonical_type() -> None:
    """A real browser sends ``audio/webm``; the route must store ``audio``.

    The DB CHECK constraint ``ck_intake_media_refs_media_type`` only admits
    ``audio``/``photo``; echoing the raw MIME type into the clip ticket used to
    surface as an IntegrityError (500) at submit (issue #375).
    """
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-media",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    media_file = facade.called_with[0][1]["file"]
    assert media_file.media_type == "audio"


def test_upload_media_photo_mime_maps_to_photo() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-media",
        files={"file": ("clip.jpg", b"jpeg-bytes", "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    media_file = facade.called_with[0][1]["file"]
    assert media_file.media_type == "photo"


def test_upload_media_rejects_duration_below_floor_at_route() -> None:
    """The query parameter enforces the 3s floor before the facade is reached."""
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-media?audio_duration_ms=2999",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert facade.called_with == []


def test_upload_media_unauthenticated_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/upload-media",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
    )

    assert response.status_code == 401


def test_upload_media_transfer_error_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = MediaTransferError("media upload failed after 3 attempts")
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-media",
        files={"file": ("clip.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "MEDIA_TRANSFER_FAILED"


# ---------------------------------------------------------------------------
# Tests: re_record
# ---------------------------------------------------------------------------


def test_re_record_returns_result() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)
    media_ref = _MEDIA_REF.model_dump(mode="json")

    response = client.post(
        "/v1/intake/42/re-record",
        json={"media_ref": media_ref},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _RERECORD_RESULT.model_dump(mode="json")
    call_kwargs = facade.called_with[0][1]
    assert call_kwargs["intake_id"] == 42
    assert call_kwargs["patient_id"] == 7
    assert call_kwargs["media_ref"] is not None


def test_re_record_unauthenticated_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/42/re-record",
        json={"media_ref": _MEDIA_REF.model_dump(mode="json")},
    )

    assert response.status_code == 401


def test_re_record_not_found_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeNotFoundError("intake 999 not found for patient 7")
    client = _client(facade)

    response = client.post(
        "/v1/intake/999/re-record",
        json={"media_ref": _MEDIA_REF.model_dump(mode="json")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"


def test_re_record_illegal_transition_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IllegalIntakeTransitionError("cannot re-record from captured")
    client = _client(facade)

    response = client.post(
        "/v1/intake/42/re-record",
        json={"media_ref": _MEDIA_REF.model_dump(mode="json")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "ILLEGAL_INTAKE_TRANSITION"


# ---------------------------------------------------------------------------
# Tests: get_intake
# ---------------------------------------------------------------------------


def test_get_intake_returns_detail_view() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.get("/v1/intake/42", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _DETAIL_VIEW.model_dump(mode="json")
    assert facade.called_with == [("get_intake", {"intake_id": 42, "patient_id": 7})]


def test_get_intake_unauthenticated_rejected() -> None:
    client = _client()

    response = client.get("/v1/intake/42")

    assert response.status_code == 401


def test_get_intake_not_found_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeNotFoundError("intake 99 not found for patient 7")
    client = _client(facade)

    response = client.get("/v1/intake/99", headers=_bearer(_token()))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: get_pre_summary
# ---------------------------------------------------------------------------


def test_get_pre_summary_returns_view() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.get("/v1/intake/42/pre-summary", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _PRE_SUMMARY_VIEW.model_dump(mode="json")
    assert facade.called_with == [("get_pre_summary", {"intake_id": 42, "patient_id": 7})]


def test_get_pre_summary_confidence_serializes_as_number() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.get("/v1/intake/42/pre-summary", headers=_bearer(_token()))

    assert response.status_code == 200
    confidence = response.json()["structuring_confidence"]
    assert isinstance(confidence, float)
    assert confidence == 0.85


def test_get_pre_summary_unauthenticated_rejected() -> None:
    client = _client()

    response = client.get("/v1/intake/42/pre-summary")

    assert response.status_code == 401


def test_get_pre_summary_not_found_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeNotFoundError("pre-summary not found for intake 42")
    client = _client(facade)

    response = client.get("/v1/intake/42/pre-summary", headers=_bearer(_token()))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Contract pin: degraded signature (ticket #391)
# ---------------------------------------------------------------------------


def test_degraded_signature_contract_ready_for_review_without_pre_summary() -> None:
    """#391: pin the API signature the degraded frontend branch depends on.

    A Ready-for-Review intake with no pre-summary row must answer the
    not-found envelope from the pre-summary endpoint while the intake-detail
    endpoint reports ``ready_for_review`` - the exact pairing the degraded
    frontend branch (tickets #389/#390) branches on. ``get_pre_summary``
    raising ``IntakeNotFoundError`` mirrors the real facade when no
    pre-summary row exists (see the facade seam in
    ``test_intake_facade_capture.py``). Pins existing behavior only - no
    endpoint change is driven here.
    """
    facade = StubIntakeFacade()
    facade.detail_view = _DETAIL_VIEW.model_copy(update={"status": "ready_for_review"})
    facade.pre_summary_error = IntakeNotFoundError("pre-summary not found for intake 42")
    client = _client(facade)
    headers = _bearer(_token())

    detail_response = client.get("/v1/intake/42", headers=headers)

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "ready_for_review"

    pre_summary_response = client.get("/v1/intake/42/pre-summary", headers=headers)

    assert pre_summary_response.status_code == 404
    assert pre_summary_response.json()["code"] == "INTAKE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: save_patient_edits
# ---------------------------------------------------------------------------


def test_save_patient_edits_returns_result() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/42/patient-edits",
        json={"fields": {"duration": "3 days, not 1 day"}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _PATIENT_EDITS_RESULT.model_dump(mode="json")
    call_kwargs = facade.called_with[0][1]
    assert call_kwargs["intake_id"] == 42
    assert call_kwargs["patient_id"] == 7
    assert call_kwargs["fields"] == {"duration": "3 days, not 1 day"}


def test_save_patient_edits_unauthenticated_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/42/patient-edits",
        json={"fields": {"duration": "3 days"}},
    )

    assert response.status_code == 401


def test_save_patient_edits_empty_fields_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/42/patient-edits",
        json={"fields": {}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_save_patient_edits_not_found_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeNotFoundError("intake 99 not found for patient 7")
    client = _client(facade)

    response = client.post(
        "/v1/intake/99/patient-edits",
        json={"fields": {"duration": "3 days"}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "INTAKE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: unknown fields rejected
# ---------------------------------------------------------------------------


def test_submit_intake_unknown_field_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/submit",
        json={"mode": "text", "language": "hi", "text": "test", "extra": "bad"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_re_record_unknown_field_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/42/re-record",
        json={"media_ref": _MEDIA_REF.model_dump(mode="json"), "extra": "bad"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: get intake media (playback, #373)
# ---------------------------------------------------------------------------


def test_get_intake_media_returns_audio_to_the_owning_patient() -> None:
    facade = StubIntakeFacade()
    facade.media_bytes = b"decrypted-audio-bytes"
    client = _client(facade)

    response = client.get(
        "/v1/intake/42/media/11",
        headers=_bearer(_token(subject_id=7)),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/webm"
    assert response.content == b"decrypted-audio-bytes"
    call_kwargs = facade.called_with[0][1]
    assert call_kwargs == {
        "intake_id": 42,
        "media_ref_id": 11,
        "caller_id": 7,
        "caller_role": "patient",
    }


def test_get_intake_media_unauthenticated_rejected() -> None:
    client = _client()

    response = client.get("/v1/intake/42/media/11")

    assert response.status_code == 401


def test_get_intake_media_not_found_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = IntakeNotFoundError("media ref 11 not found on intake 42")
    client = _client(facade)

    response = client.get(
        "/v1/intake/42/media/11",
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "INTAKE_NOT_FOUND"


def test_get_intake_media_transfer_failure_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = MediaTransferError("failed to read media ref 11")
    client = _client(facade)

    response = client.get(
        "/v1/intake/42/media/11",
        headers=_bearer(_token()),
    )

    assert response.status_code == 502
    assert response.json()["code"] == "MEDIA_TRANSFER_FAILED"


# ---------------------------------------------------------------------------
# Tests: intake surface rate limiting (PS-05, #403)
# ---------------------------------------------------------------------------


def test_submit_exhausted_cap_answers_429_with_retry_after() -> None:
    """AC2: a row-writing intake route answers the shared 429 when the tier empties.

    The limiter runs before ``jwt_verify``, so the exhausted response is the
    shared gateway envelope - ``RATE_LIMIT_EXCEEDED`` with a trace id and a
    ``Retry-After`` header - never the route's own error shape.
    """
    client = _rate_limited_client(max_requests=2)
    headers = _bearer(_token())
    body = {"mode": "text", "language": "hi", "text": "Mujhe sar dard hai"}

    assert client.post("/v1/intake/submit", json=body, headers=headers).status_code == 200
    assert client.post("/v1/intake/submit", json=body, headers=headers).status_code == 200

    response = client.post("/v1/intake/submit", json=body, headers=headers)

    assert response.status_code == 429
    body_429 = response.json()
    assert body_429["code"] == "RATE_LIMIT_EXCEEDED"
    assert body_429["trace_id"]
    assert body_429["details"] == {}
    assert response.headers["Retry-After"] == "60"


def test_upload_media_exhausted_cap_answers_429_with_retry_after() -> None:
    """AC2 for the media-writing surface: uploads exhaust their own 429 tier."""
    client = _rate_limited_client(max_requests=2)
    headers = _bearer(_token())
    files = {"file": ("clip.webm", b"audio-bytes", "audio/webm")}

    assert client.post("/v1/intake/upload-media", files=files, headers=headers).status_code == 200
    assert client.post("/v1/intake/upload-media", files=files, headers=headers).status_code == 200

    response = client.post("/v1/intake/upload-media", files=files, headers=headers)

    assert response.status_code == 429
    body_429 = response.json()
    assert body_429["code"] == "RATE_LIMIT_EXCEEDED"
    assert body_429["trace_id"]
    assert body_429["details"] == {}
    assert response.headers["Retry-After"] == "60"


def test_re_record_exhausted_cap_answers_429_with_retry_after() -> None:
    """AC2 for the re-record surface: the dynamic-path write answers 429 too."""
    client = _rate_limited_client(max_requests=2)
    headers = _bearer(_token())
    payload = {"media_ref": _MEDIA_REF.model_dump(mode="json")}

    assert client.post("/v1/intake/42/re-record", json=payload, headers=headers).status_code == 200
    assert client.post("/v1/intake/42/re-record", json=payload, headers=headers).status_code == 200

    response = client.post("/v1/intake/42/re-record", json=payload, headers=headers)

    assert response.status_code == 429
    body_429 = response.json()
    assert body_429["code"] == "RATE_LIMIT_EXCEEDED"
    assert body_429["trace_id"]
    assert body_429["details"] == {}
    assert response.headers["Retry-After"] == "60"


def test_intake_reads_bypass_rate_cap() -> None:
    """The write tier never caps the read surfaces.

    Exhausting submit still leaves the intake detail, pre-summary, and clip
    playback routes answering normally - the limiter matches only the
    media-and-row-writing trio, not ``/v1/intake/*`` wholesale.
    """
    client = _rate_limited_client(max_requests=2)
    headers = _bearer(_token())
    body = {"mode": "text", "language": "hi", "text": "Mujhe sar dard hai"}

    assert client.post("/v1/intake/submit", json=body, headers=headers).status_code == 200
    assert client.post("/v1/intake/submit", json=body, headers=headers).status_code == 200
    assert client.post("/v1/intake/submit", json=body, headers=headers).status_code == 429

    assert client.get("/v1/intake/42", headers=headers).status_code == 200
    assert client.get("/v1/intake/42/pre-summary", headers=headers).status_code == 200
    assert client.get("/v1/intake/42/media/11", headers=headers).status_code == 200
