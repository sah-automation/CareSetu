"""PHASE-8.1 T04: POST /v1/intake/upload-doctor-media doctor route (ticket #481).

The route is a thin adapter: resolve the partner principal, refuse any
non-doctor partner, wrap the uploaded bytes in a ``MediaFile`` (canonical
type for voice or photo), call the intake facade's
``upload_doctor_input_media``, and answer the typed ``MediaUploadRef`` shape.
Both facades are stubbed here - the encrypted ``rx_input/`` storage and the
retry behavior are the facade/store suite's job. Every expected failure
answers the shared error envelope (api-standards S2). Doctor RBAC is partner
scope + ``partner_type == "doctor"``: unauthenticated (401), patient (403),
and non-doctor partner scopes (403) are rejected at the edge.
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
from modules.intake.domain.exceptions import MediaTransferError
from modules.intake.intake_models import MediaFile, MediaUploadRef
from modules.partner.facade import PartnerView

_SIGNING_KEY = "test-doctor-media-upload-route-signing-key"

_PARTNER_ID = 12
_DOCTOR_IDENTITY = 30

_MEDIA_REF = MediaUploadRef(
    object_key="rx_input/12/clip-abc.webm",
    media_type="audio",
    audio_duration_ms=5000,
    file_size_bytes=12000,
    record_attempt=1,
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
    """Minimal intake facade stand-in recording calls and replaying a canned ticket."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []
        self.media_ref: MediaUploadRef = _MEDIA_REF
        self.error: Exception | None = None

    async def upload_doctor_input_media(self, **kwargs: object) -> MediaUploadRef:
        self.called_with.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.media_ref


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


def test_doctor_upload_returns_media_ticket() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-doctor-media?audio_duration_ms=5000",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object_key"] == "rx_input/12/clip-abc.webm"
    assert body["media_type"] == "audio"
    assert body["audio_duration_ms"] == 5000

    kwargs = facade.called_with[0]
    assert kwargs["doctor_id"] == _PARTNER_ID
    media_file = kwargs["file"]
    assert isinstance(media_file, MediaFile)
    assert media_file.data == b"audio-bytes"
    assert media_file.media_type == "audio"
    assert media_file.audio_duration_ms == 5000
    assert media_file.file_size_bytes == len(b"audio-bytes")


def test_doctor_upload_photo_mime_maps_to_photo() -> None:
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-doctor-media",
        files={"file": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    media_file = facade.called_with[0]["file"]
    assert media_file.media_type == "photo"


def test_doctor_upload_rejects_duration_below_floor_at_route() -> None:
    """The query parameter enforces the 3s floor before the facade is reached."""
    facade = StubIntakeFacade()
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-doctor-media?audio_duration_ms=2999",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert facade.called_with == []


def test_doctor_upload_transfer_error_envelope() -> None:
    facade = StubIntakeFacade()
    facade.error = MediaTransferError("media upload failed after 3 attempts for doctor 12")
    client = _client(facade)

    response = client.post(
        "/v1/intake/upload-doctor-media",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 502
    assert response.json()["code"] == "MEDIA_TRANSFER_FAILED"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_doctor_upload_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/upload-doctor-media",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_doctor_upload_patient_scope_rejected_with_403() -> None:
    client = _client()

    response = client.post(
        "/v1/intake/upload-doctor-media",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token(scope="patient")),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_doctor_upload_non_doctor_partner_rejected_with_403() -> None:
    partner_facade = StubPartnerFacade(partner_type="lab")
    client = _client(partner_facade=partner_facade)

    response = client.post(
        "/v1/intake/upload-doctor-media",
        files={"file": ("note.webm", b"audio-bytes", "audio/webm")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_doctor_upload_route_sits_behind_the_gateway_stack() -> None:
    app = create_app(
        settings=Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    )

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert RateLimitMiddleware in middlewares
    assert TraceMiddleware in middlewares
    assert "/v1/intake/upload-doctor-media" in app.openapi()["paths"]
