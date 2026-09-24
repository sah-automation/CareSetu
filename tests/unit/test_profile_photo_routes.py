"""US-20 (#533): PUT/GET/DELETE /v1/me/photo HTTP adapters + photo contract.

Thin adapters like the /v1/me/profile surface: read the multipart file (PUT),
call the iam facade's photo seam (``save_patient_photo`` /
``get_patient_photo`` / ``delete_patient_photo``), and answer the typed
``PatientProfileResponse`` (mutations) or a streamed ``Response`` (GET). All
three routes are ``require_authenticated``-gated like the rest of ``/v1/me`` -
anonymous callers are 401. The facade is stubbed here; the encrypted
``profile-media`` storage, the retry ladder, and the row persistence are the
facade/store suites' job. The photo contract (JPEG/PNG/WebP only - GIF
refused - and a 5MB ceiling) is exercised through the real
``validate_profile_photo`` helper the stub calls, so the 422 path is faithful.
Every expected failure answers the shared error envelope (api-standards §2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.idempotency import IdempotencyStore
from app.main import create_app
from modules.iam.domain.exceptions import (
    IamError,
    PatientProfileNotSetError,
    ProfilePhotoTransferError,
    ProfilePhotoValidationError,
)
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import PatientProfile, PhotoContent
from modules.iam.identity_facade import (
    MAX_PROFILE_PHOTO_BYTES,
    _sniff_image_media_type,
    validate_profile_photo,
)

_SIGNING_KEY = "test-profile-photo-route-signing-key"

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 100


def _token(*, subject_id: int = 1, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _profile(*, photo_ref: str | None = None) -> PatientProfile:
    return PatientProfile(
        name="Asha Devi",
        age=34,
        gender="female",
        preferred_language="hi",
        area="Daltonganj",
        emergency_contact="+9199876543211",
        photo_ref=photo_ref,
    )


class StubPhotoFacade:
    """Identity-facade stand-in for the photo surface, per identity id.

    Mirrors the real facade's semantics in memory: the photo contract is
    enforced through the real ``validate_profile_photo`` before anything is
    stored, the photo bytes are keyed by ``identity_id`` (never a public URL),
    and ``photo_ref`` is threaded onto the profile. The store failure shapes
    (retry ladder exhaustion, missing stored object) are exercised here by
    raising the same domain errors the real facade raises.
    """

    def __init__(self) -> None:
        self.profiles: dict[int, PatientProfile] = {}
        self.stored: dict[int, bytes] = {}
        self.deleted_refs: list[str] = []
        self.save_calls: list[tuple[int, bytes, str | None]] = []
        self.ref_counters: dict[int, int] = {}
        self.error: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def get_patient_profile(self, identity_id: int) -> PatientProfile | None:
        self._maybe_raise()
        return self.profiles.get(identity_id)

    async def save_patient_photo(
        self,
        *,
        identity_id: int,
        data: bytes,
        media_type: str | None,
    ) -> PatientProfile:
        self._maybe_raise()
        validate_profile_photo(media_type, data)
        profile = self.profiles.get(identity_id)
        if profile is None:
            raise PatientProfileNotSetError(
                "set the patient profile before uploading a profile photo"
            )
        self.save_calls.append((identity_id, data, media_type))
        old_ref = profile.photo_ref
        self.stored[identity_id] = data
        # The real store mints a fresh opaque key per save, so the replace
        # always supersedes the previous ref (never a same-key overwrite).
        counter = self.ref_counters.get(identity_id, 0) + 1
        self.ref_counters[identity_id] = counter
        new_ref = f"patient/{identity_id}/photo-{counter}.jpg"
        profile.photo_ref = new_ref
        if old_ref is not None and old_ref != new_ref:
            self.deleted_refs.append(old_ref)
        return profile

    async def get_patient_photo(self, *, identity_id: int) -> PhotoContent | None:
        self._maybe_raise()
        data = self.stored.get(identity_id)
        if data is None:
            return None
        return PhotoContent(data=data, media_type=_sniff_image_media_type(data))

    async def delete_patient_photo(self, *, identity_id: int) -> PatientProfile:
        self._maybe_raise()
        profile = self.profiles.get(identity_id)
        if profile is None:
            raise PatientProfileNotSetError(
                "set the patient profile before removing a profile photo"
            )
        if profile.photo_ref is None:
            return profile
        self.deleted_refs.append(profile.photo_ref)
        self.stored.pop(identity_id, None)
        profile.photo_ref = None
        return profile


def _client(profile_facade: StubPhotoFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.iam_facade = profile_facade if profile_facade is not None else StubPhotoFacade()
    return TestClient(app)


def _client_with_store(facade: StubPhotoFacade, store: IdempotencyStore) -> TestClient:
    client = _client(profile_facade=facade)
    client.app.state.idempotency_store = store
    return client


# ---------------------------------------------------------------------------
# Photo contract helpers (US-20)
# ---------------------------------------------------------------------------


def test_validate_photo_admits_jpeg_png_webp_and_bounds() -> None:
    validate_profile_photo("image/jpeg", _JPEG_BYTES)
    validate_profile_photo("image/png", _PNG_BYTES)
    validate_profile_photo("image/webp", _WEBP_BYTES)
    # A ``; charset=``-style suffix on the content type is still JPEG.
    validate_profile_photo("image/jpeg; charset=binary", _JPEG_BYTES)
    # The ceiling is inclusive: exactly 5MB is accepted.
    validate_profile_photo("image/jpeg", b"\x00" * MAX_PROFILE_PHOTO_BYTES)


def test_validate_photo_refuses_gif_missing_and_oversized_uploads() -> None:
    with pytest.raises(ProfilePhotoValidationError):
        validate_profile_photo("image/gif", _JPEG_BYTES)
    with pytest.raises(ProfilePhotoValidationError):
        validate_profile_photo(None, _JPEG_BYTES)
    with pytest.raises(ProfilePhotoValidationError):
        validate_profile_photo("image/png", b"\x00" * (MAX_PROFILE_PHOTO_BYTES + 1))


def test_sniff_image_media_type_reads_magic_bytes() -> None:
    assert _sniff_image_media_type(_JPEG_BYTES) == "image/jpeg"
    assert _sniff_image_media_type(_PNG_BYTES) == "image/png"
    assert _sniff_image_media_type(_WEBP_BYTES) == "image/webp"
    assert _sniff_image_media_type(b"not an image") == "application/octet-stream"


# ---------------------------------------------------------------------------
# PUT: upload/replace
# ---------------------------------------------------------------------------


def test_put_uploads_the_photo_and_answers_the_updated_profile() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "set": True,
        "profile": _profile(photo_ref="patient/1/photo-1.jpg").model_dump(mode="json"),
    }
    assert facade.save_calls == [(1, _JPEG_BYTES, "image/jpeg")]


def test_put_requires_a_saved_profile_with_409_not_set() -> None:
    client = _client()

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PROFILE_NOT_SET"


def test_put_refuses_gif_with_422_invalid() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.gif", _JPEG_BYTES, "image/gif")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PROFILE_PHOTO_INVALID"
    assert facade.save_calls == []
    assert facade.stored == {}


def test_put_refuses_oversized_photo_with_422_invalid() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", b"\x00" * (MAX_PROFILE_PHOTO_BYTES + 1), "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PROFILE_PHOTO_INVALID"
    assert facade.save_calls == []


def test_put_without_a_file_part_is_a_validation_422() -> None:
    client = _client()

    response = client.put("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_put_replaces_an_existing_photo_and_retires_the_old_ref() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _PNG_BYTES, "image/png")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.stored[1] == _PNG_BYTES
    assert facade.profiles[1].photo_ref == "patient/1/photo-1.jpg"
    assert facade.deleted_refs == ["patient/1/photo.jpg"]


def test_put_upload_to_the_gateway_without_profile_keeps_other_identities_intact() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client(profile_facade=facade)

    other = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _PNG_BYTES, "image/webp")},
        headers=_bearer(_token(subject_id=2)),
    )

    assert other.status_code == 409
    # Identity 1's stored photo is untouched by identity 2's failed upload.
    assert facade.stored[1] == _JPEG_BYTES
    assert facade.profiles[1].photo_ref == "patient/1/photo.jpg"
    assert facade.save_calls == []


# ---------------------------------------------------------------------------
# GET: stream preview
# ---------------------------------------------------------------------------


def test_get_streams_the_stored_photo_with_its_content_type() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client(profile_facade=facade)

    response = client.get("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.content == _JPEG_BYTES
    assert response.headers["content-type"].startswith("image/jpeg")


def test_get_without_a_photo_answers_404_not_found() -> None:
    client = _client()

    response = client.get("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "PROFILE_PHOTO_NOT_FOUND"
    assert body["message"]


def test_get_after_delete_answers_404_not_found() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client(profile_facade=facade)
    client.delete("/v1/me/photo", headers=_bearer(_token()))

    response = client.get("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 404
    assert response.json()["code"] == "PROFILE_PHOTO_NOT_FOUND"


def test_get_streams_the_correct_identity_photo_without_leakage() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _PNG_BYTES
    facade.profiles[2] = _profile(photo_ref="patient/2/photo.jpg")
    facade.stored[2] = _WEBP_BYTES
    client = _client(profile_facade=facade)

    first = client.get("/v1/me/photo", headers=_bearer(_token(subject_id=1)))
    second = client.get("/v1/me/photo", headers=_bearer(_token(subject_id=2)))

    assert first.content == _PNG_BYTES
    assert second.content == _WEBP_BYTES
    assert first.headers["content-type"].startswith("image/png")
    assert second.headers["content-type"].startswith("image/webp")


# ---------------------------------------------------------------------------
# DELETE: remove
# ---------------------------------------------------------------------------


def test_delete_clears_the_photo_and_retires_the_ref() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client(profile_facade=facade)

    response = client.delete("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["set"] is True
    assert body["profile"]["photo_ref"] is None
    assert facade.stored == {}
    assert facade.deleted_refs == ["patient/1/photo.jpg"]


def test_delete_is_idempotent_without_a_photo() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)

    response = client.delete("/v1/me/photo", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json()["profile"]["photo_ref"] is None
    assert facade.deleted_refs == []


def test_put_get_delete_round_trip() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)

    put = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=_bearer(_token()),
    )
    preview = client.get("/v1/me/photo", headers=_bearer(_token()))
    gone = client.delete("/v1/me/photo", headers=_bearer(_token()))
    after = client.get("/v1/me/photo", headers=_bearer(_token()))

    assert put.status_code == 200
    assert preview.status_code == 200
    assert preview.content == _JPEG_BYTES
    assert gone.status_code == 200
    assert gone.json()["profile"]["photo_ref"] is None
    assert after.status_code == 404


# ---------------------------------------------------------------------------
# AuthN + shared error envelope
# ---------------------------------------------------------------------------


def test_all_three_verbs_reject_anonymous_callers_with_401() -> None:
    client = _client()

    put = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
    )
    get = client.get("/v1/me/photo")
    delete = client.delete("/v1/me/photo")

    for response in (put, get, delete):
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_transfer_failure_answers_502_envelope() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    facade.error = ProfilePhotoTransferError(
        "profile photo upload failed after 3 attempts for patient 1"
    )
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 502
    assert response.json()["code"] == "PROFILE_PHOTO_TRANSFER_FAILED"


def test_unexpected_iam_error_answers_500_envelope_without_leaking() -> None:
    facade = StubPhotoFacade()
    facade.error = IamError("boom-with-a-secret")
    client = _client(profile_facade=facade)

    response = client.put(
        "/v1/me/photo",
        files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "boom-with-a-secret" not in body["message"]


# ---------------------------------------------------------------------------
# Idempotency-Key on the mutations (api-standards §5)
# ---------------------------------------------------------------------------


def test_put_replays_same_key_without_second_facade_call() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client_with_store(facade, IdempotencyStore())
    headers = {**_bearer(_token()), "Idempotency-Key": "retry-photo-123"}
    files = {"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")}

    first = client.put("/v1/me/photo", files=files, headers=headers)
    replay = client.put("/v1/me/photo", files=files, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(facade.save_calls) == 1
    assert facade.stored[1] == _JPEG_BYTES


def test_delete_replays_same_key_without_second_facade_call() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile(photo_ref="patient/1/photo.jpg")
    facade.stored[1] = _JPEG_BYTES
    client = _client_with_store(facade, IdempotencyStore())
    headers = {**_bearer(_token()), "Idempotency-Key": "retry-rm-photo-1"}

    first = client.delete("/v1/me/photo", headers=headers)
    replay = client.delete("/v1/me/photo", headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert facade.deleted_refs == ["patient/1/photo.jpg"]


def test_put_different_keys_execute_each_mutation() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client_with_store(facade, IdempotencyStore())
    files = {"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")}

    client.put(
        "/v1/me/photo",
        files=files,
        headers={**_bearer(_token()), "Idempotency-Key": "k-1"},
    )
    client.put(
        "/v1/me/photo",
        files=files,
        headers={**_bearer(_token()), "Idempotency-Key": "k-2"},
    )

    assert len(facade.save_calls) == 2
    assert facade.ref_counters[1] == 2


def test_put_no_key_passes_through_without_store_interaction() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    client = _client(profile_facade=facade)
    files = {"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")}

    client.put("/v1/me/photo", files=files, headers=_bearer(_token()))
    client.put("/v1/me/photo", files=files, headers=_bearer(_token()))

    assert len(facade.save_calls) == 2


def test_same_key_across_identities_never_replays_anothers_photo() -> None:
    facade = StubPhotoFacade()
    facade.profiles[1] = _profile()
    facade.profiles[2] = _profile()
    client = _client_with_store(facade, IdempotencyStore())
    shared = {"Idempotency-Key": "k-shared"}
    files1 = {"file": ("first.jpg", _JPEG_BYTES, "image/jpeg")}
    files2 = {"file": ("second.jpg", _PNG_BYTES, "image/png")}

    client.put("/v1/me/photo", files=files1, headers={**_bearer(_token(subject_id=1)), **shared})
    second_put = client.put(
        "/v1/me/photo", files=files2, headers={**_bearer(_token(subject_id=2)), **shared}
    )
    second_get = client.get("/v1/me/photo", headers=_bearer(_token(subject_id=2)))

    assert second_put.status_code == 200
    # The shared key must NOT hand identity 2 identity 1's cached photo; the
    # replay cache is namespaced per principal, so identity 2's own upload runs.
    assert second_get.content == _PNG_BYTES
    assert len(facade.save_calls) == 2


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_photo_routes_sit_behind_the_gateway_stack() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/me/photo" in paths
    assert set(paths["/v1/me/photo"]) == {"get", "put", "delete"}
