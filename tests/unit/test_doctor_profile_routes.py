from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import PhotoContent
from modules.partner.doctor_profile_models import (
    DoctorProfileCredential,
    DoctorProfilePhotoView,
    DoctorProfileUpdate,
    DoctorProfileView,
)
from modules.partner.facade import (
    DoctorProfileNotAllowedError,
    DoctorProfilePhotoNotFoundError,
    DoctorProfilePhotoValidationError,
    PartnerView,
)

_SIGNING_KEY = "test-doctor-profile-route-signing-key"
_PARTNER_ID = 12
_IDENTITY_ID = 30
_OTHER_PARTNER_ID = 13
_OTHER_IDENTITY_ID = 31


def _token(*, subject_id: int = _IDENTITY_ID, scope: str = "partner") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class StubIamFacade:
    def __init__(self) -> None:
        self.access_denials: list[int] = []

    async def emit_access_denied(self, identity_id: int) -> None:
        self.access_denials.append(identity_id)


class StubPartnerFacade:
    def __init__(self) -> None:
        self.profile_calls: list[int] = []
        self.update_calls: list[tuple[int, DoctorProfileUpdate]] = []
        self.photo_update_calls: list[tuple[int, str | None, bytes]] = []
        self.photo_get_calls: list[int] = []
        self.photo_delete_calls: list[int] = []
        self.photo = PhotoContent(data=b"photo-bytes", media_type="image/jpeg")
        self.photo_error: Exception | None = None
        self.profile_error: Exception | None = None
        self.identity_partner_ids = {
            _IDENTITY_ID: _PARTNER_ID,
            _OTHER_IDENTITY_ID: _OTHER_PARTNER_ID,
        }
        self.partner_type = "doctor"
        self.partner_status = "Active"
        self.view = DoctorProfileView(
            partner_id=_PARTNER_ID,
            photo_ref="doctor/12/photo.enc",
            practice_name="Shanti Clinic",
            specialty="General Physician",
            verified=True,
            practice_address="Main Road, Daltonganj",
            practice_latitude=24.483,
            practice_longitude=87.433,
            area="Daltonganj",
            languages=["English", "Hindi"],
            experience_years=12,
            about="Primary care physician.",
            consultation_fee=50000,
            availability="Monday to Friday, 9 AM to 5 PM",
            credentials=[
                DoctorProfileCredential(
                    credential_type="medical_registration",
                    status="verified",
                    expires_at=datetime.now(UTC) + timedelta(days=180),
                )
            ],
            notification_preferences={"appointment_reminders": True, "sms": True},
        )

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        return PartnerView(
            partner_id=self.identity_partner_ids[identity_id],
            partner_type=self.partner_type,
            status=self.partner_status,
            round=1,
        )

    async def get_doctor_profile(self, doctor_id: int) -> DoctorProfileView:
        self.profile_calls.append(doctor_id)
        if self.profile_error is not None:
            raise self.profile_error
        return self.view

    async def update_doctor_profile(
        self,
        doctor_id: int,
        update: DoctorProfileUpdate,
    ) -> DoctorProfileView:
        self.update_calls.append((doctor_id, update))
        return self.view

    async def update_doctor_photo(
        self,
        doctor_id: int,
        *,
        media_type: str | None,
        data: bytes,
    ) -> DoctorProfilePhotoView:
        self.photo_update_calls.append((doctor_id, media_type, data))
        if self.photo_error is not None:
            raise self.photo_error
        return DoctorProfilePhotoView(photo_ref="doctor/12/photo.enc")

    async def get_doctor_photo(self, doctor_id: int) -> PhotoContent:
        self.photo_get_calls.append(doctor_id)
        if self.photo_error is not None:
            raise self.photo_error
        return self.photo

    async def delete_doctor_photo(self, doctor_id: int) -> None:
        self.photo_delete_calls.append(doctor_id)
        return None


def _client(facade: StubPartnerFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.partner_facade = facade if facade is not None else StubPartnerFacade()
    app.state.iam_facade = StubIamFacade()
    return TestClient(app)


def test_get_doctor_profile_returns_private_projection_for_active_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get("/v1/doctor/profile", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert facade.profile_calls == [_PARTNER_ID]


def test_facade_profile_authorization_denial_is_audited() -> None:
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.get("/v1/doctor/profile", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


def test_put_doctor_profile_updates_editable_fields_for_active_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "practice_name": "Shanti Clinic",
        "practice_address": "Main Road, Daltonganj",
        "practice_latitude": 24.483,
        "practice_longitude": 87.433,
        "experience_years": 12,
        "languages": ["English", "Hindi"],
        "about": "Primary care physician.",
        "availability": "Monday to Friday, 9 AM to 5 PM",
        "notification_preferences": {"appointment_reminders": True, "sms": True},
    }

    response = client.put("/v1/doctor/profile", json=body, headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert len(facade.update_calls) == 1
    doctor_id, update = facade.update_calls[0]
    assert doctor_id == _PARTNER_ID
    assert update.model_dump(mode="json") == body


def test_profile_idempotency_key_is_scoped_to_the_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "practice_address": "Main Road, Daltonganj",
        "practice_latitude": 24.483,
        "practice_longitude": 87.433,
    }
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-profile-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-profile-key",
    }

    first = client.put("/v1/doctor/profile", json=body, headers=first_headers)
    second = client.put("/v1/doctor/profile", json=body, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _ in facade.update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_put_doctor_profile_photo_uploads_private_doctor_media() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == {"photo_ref": "doctor/12/photo.enc"}
    assert facade.photo_update_calls == [(_PARTNER_ID, "image/jpeg", b"photo-bytes")]


def test_photo_idempotency_key_is_scoped_to_the_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-photo-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-photo-key",
    }

    first = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=first_headers,
    )
    second = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=second_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _, _ in facade.photo_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_get_doctor_profile_photo_streams_private_bytes() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.content == b"photo-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert facade.photo_get_calls == [_PARTNER_ID]


def test_get_doctor_profile_photo_returns_404_when_unset() -> None:
    facade = StubPartnerFacade()
    facade.photo_error = DoctorProfilePhotoNotFoundError(_PARTNER_ID)
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCTOR_PROFILE_PHOTO_NOT_FOUND"


def test_put_doctor_profile_photo_maps_validation_failure() -> None:
    facade = StubPartnerFacade()
    facade.photo_error = DoctorProfilePhotoValidationError("invalid photo")
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.gif", b"GIF89a", "image/gif")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "DOCTOR_PROFILE_PHOTO_INVALID"
    assert response.json()["details"]["errors"] == [{"path": "file", "reason": "invalid photo"}]


def test_get_doctor_profile_photo_refuses_non_active_doctor() -> None:
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.photo_get_calls == []


def test_delete_doctor_profile_photo_returns_no_content() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.delete(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert facade.photo_delete_calls == [_PARTNER_ID]


def test_delete_doctor_profile_photo_replays_the_same_idempotency_key() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    headers = {
        **_bearer(_token()),
        "Idempotency-Key": "delete-photo-key",
    }

    first = client.delete("/v1/doctor/profile/photo", headers=headers)
    second = client.delete("/v1/doctor/profile/photo", headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    assert facade.photo_delete_calls == [_PARTNER_ID]
