from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.partner.doctor_profile_models import DoctorProfileUpdate
from modules.partner.facade import (
    DoctorProfileNotAllowedError,
    DoctorProfilePhotoNotFoundError,
    DoctorProfilePhotoStoreUnavailableError,
    DoctorProfilePhotoValidationError,
    PartnerFacade,
)
from modules.profile_media.facade import ProfileMediaStoreError

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class _Row:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


class _Result:
    def __init__(self, *, row: object = None, rows: list[object] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def first(self) -> object:
        return self._row

    def all(self) -> list[object]:
        return self._rows


class _Cache:
    def __init__(self) -> None:
        self.visibility_changes = 0

    async def directory_visibility_changed(self) -> None:
        self.visibility_changes += 1


class _MediaStore:
    def __init__(self) -> None:
        self.saved: list[tuple[bytes, int, str]] = []
        self.save_attempts = 0
        self.save_error: Exception | None = None
        self.read_keys: list[str] = []
        self.deleted: list[str] = []
        self.stored: dict[str, bytes] = {}
        self.read_error: Exception | None = None

    async def save(self, *, data: bytes, subject_id: int, prefix: str) -> str:
        self.save_attempts += 1
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((data, subject_id, prefix))
        key = f"{prefix}/{subject_id}/new-photo.enc"
        self.stored[key] = data
        return key

    async def read(self, *, object_key: str) -> bytes:
        self.read_keys.append(object_key)
        if self.read_error is not None:
            raise self.read_error
        return self.stored[object_key]

    async def delete(self, *, object_key: str) -> None:
        self.deleted.append(object_key)
        self.stored.pop(object_key, None)

    async def close(self) -> None:
        return None


def _connection(results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=results)
    return connection


def _facade(
    connection: AsyncMock,
    *,
    media_store: _MediaStore | None = None,
) -> PartnerFacade:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return PartnerFacade(
        engine=engine,
        clock=lambda: _NOW,
        profile_media_store=media_store,
        doctor_profile_photo_max_bytes=5 * 1024 * 1024,
    )


@pytest.mark.asyncio
async def test_get_doctor_profile_projects_private_fields_and_derived_status() -> None:
    expires_at = _NOW + timedelta(days=180)
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_id=12,
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                    practice_name="Shanti Clinic",
                    specialty="General Physician",
                    practice_address="Main Road, Daltonganj",
                    practice_latitude=24.483,
                    practice_longitude=87.433,
                    area_name="Daltonganj",
                    languages=["English", "Hindi"],
                    experience_years=12,
                    about="Primary care physician.",
                    consultation_fee_paise=50000,
                    availability="Monday to Friday, 9 AM to 5 PM",
                    notification_preferences={"appointment_reminders": True, "sms": True},
                )
            ),
            _Result(
                rows=[
                    _Row(
                        credential_type="medical_registration",
                        verified=True,
                        expires_at=expires_at,
                        revoked_at=None,
                        invalidation_reason=None,
                    ),
                    _Row(
                        credential_type="qualification_certificate",
                        verified=False,
                        expires_at=None,
                        revoked_at=None,
                        invalidation_reason=None,
                    ),
                ]
            ),
        ]
    )
    facade = _facade(connection)

    profile = await facade.get_doctor_profile(12)

    assert profile.partner_id == 12
    assert profile.photo_ref == "doctor/12/photo.enc"
    assert profile.practice_name == "Shanti Clinic"
    assert profile.specialty == "General Physician"
    assert profile.verified is True
    assert profile.practice_address == "Main Road, Daltonganj"
    assert profile.practice_latitude == pytest.approx(24.483)
    assert profile.practice_longitude == pytest.approx(87.433)
    assert profile.area == "Daltonganj"
    assert profile.languages == ["English", "Hindi"]
    assert profile.experience_years == 12
    assert profile.about == "Primary care physician."
    assert profile.consultation_fee == 50000
    assert profile.availability == "Monday to Friday, 9 AM to 5 PM"
    assert profile.notification_preferences == {"appointment_reminders": True, "sms": True}
    assert [credential.model_dump(mode="json") for credential in profile.credentials] == [
        {
            "credential_type": "medical_registration",
            "status": "verified",
            "expires_at": "2027-03-24T12:00:00Z",
        },
        {
            "credential_type": "qualification_certificate",
            "status": "pending",
            "expires_at": None,
        },
    ]


@pytest.mark.asyncio
async def test_update_doctor_profile_writes_shared_row_and_directory_geo() -> None:
    update = DoctorProfileUpdate(
        practice_name="Shanti Clinic",
        practice_address="Main Road, Daltonganj",
        practice_latitude=24.483,
        practice_longitude=87.433,
        experience_years=12,
        languages=["English", "Hindi"],
        about="Primary care physician.",
        availability="Monday to Friday, 9 AM to 5 PM",
        notification_preferences={"appointment_reminders": True, "sms": True},
    )
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(),
            _Result(),
            _Result(
                row=_Row(
                    partner_id=12,
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                    practice_name="Shanti Clinic",
                    specialty="General Physician",
                    practice_address="Main Road, Daltonganj",
                    practice_latitude=24.483,
                    practice_longitude=87.433,
                    area_name="Daltonganj",
                    languages=["English", "Hindi"],
                    experience_years=12,
                    about="Primary care physician.",
                    consultation_fee_paise=50000,
                    availability="Monday to Friday, 9 AM to 5 PM",
                    notification_preferences={"appointment_reminders": True, "sms": True},
                )
            ),
            _Result(
                rows=[
                    _Row(
                        credential_type="medical_registration",
                        verified=True,
                        expires_at=_NOW + timedelta(days=180),
                        revoked_at=None,
                        invalidation_reason=None,
                    )
                ]
            ),
        ]
    )
    facade = _facade(connection)
    cache = _Cache()
    facade._directory_cache = cache

    profile = await facade.update_doctor_profile(12, update)

    assert profile.practice_name == "Shanti Clinic"
    assert profile.consultation_fee == 50000
    statements = [call.args[0] for call in connection.execute.await_args_list]
    profile_update = statements[1]
    directory_update = statements[2]
    assert profile_update.table.name == "partner_profiles"
    assert profile_update._values["practice_name"].value == "Shanti Clinic"
    assert profile_update._values["languages"].value == ["English", "Hindi"]
    assert "consultation_fee_paise" not in profile_update._values
    assert directory_update.table.name == "partner_directory_index"
    assert directory_update._values["practice_latitude"].value == 24.483
    assert directory_update._values["practice_longitude"].value == 87.433
    assert cache.visibility_changes == 1


@pytest.mark.asyncio
async def test_registered_doctor_cannot_read_or_update_profile() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.get_doctor_profile(12)
    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_profile(
            12,
            DoctorProfileUpdate(
                practice_address="Main Road",
                practice_latitude=24.483,
                practice_longitude=87.433,
            ),
        )

    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_registered_doctor_cannot_upload_or_read_photo() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    store = _MediaStore()
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )
    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.get_doctor_photo(12)

    assert store.saved == []
    assert store.read_keys == []


@pytest.mark.asyncio
async def test_registered_doctor_cannot_delete_photo() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    store = _MediaStore()
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.delete_doctor_photo(12)

    assert store.deleted == []


@pytest.mark.asyncio
async def test_update_doctor_photo_maps_permanent_storage_error() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    store = _MediaStore()
    store.save_error = ProfileMediaStoreError(
        "storage rejected object",
        retryable=False,
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfilePhotoStoreUnavailableError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )

    assert store.save_attempts == 1


@pytest.mark.asyncio
async def test_update_doctor_photo_rejects_configured_size_limit() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    facade = _facade(connection, media_store=_MediaStore())

    with pytest.raises(DoctorProfilePhotoValidationError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=b"x" * (5 * 1024 * 1024 + 1),
        )


@pytest.mark.asyncio
async def test_update_doctor_photo_persists_doctor_prefix_key_and_retires_old_object() -> None:
    store = _MediaStore()
    store.stored["doctor/12/observed-photo.enc"] = b"old"
    store.stored["doctor/12/latest-photo.enc"] = b"latest"
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/observed-photo.enc",
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/latest-photo.enc",
                )
            ),
            _Result(),
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.update_doctor_photo(
        12,
        media_type="image/jpeg",
        data=_JPEG_BYTES,
    )

    assert result.photo_ref == "doctor/12/new-photo.enc"
    assert store.saved == [(_JPEG_BYTES, 12, "doctor")]
    locked_swap = connection.execute.await_args_list[1].args[0]
    assert "FOR UPDATE" in str(locked_swap)
    update = connection.execute.await_args_list[2].args[0]
    assert update.table.name == "partner_profiles"
    assert update._values["photo_ref"].value == "doctor/12/new-photo.enc"
    assert store.deleted == ["doctor/12/latest-photo.enc"]


@pytest.mark.asyncio
async def test_update_doctor_photo_rechecks_active_doctor_before_ref_swap() -> None:
    store = _MediaStore()
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )

    assert store.deleted == ["doctor/12/new-photo.enc"]


@pytest.mark.asyncio
async def test_get_doctor_photo_streams_private_bytes_from_canonical_ref() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.enc"] = _JPEG_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.get_doctor_photo(12)

    assert result is not None
    assert result.data == _JPEG_BYTES
    assert result.media_type == "image/jpeg"
    assert store.read_keys == ["doctor/12/photo.enc"]


@pytest.mark.asyncio
async def test_get_doctor_photo_returns_not_found_without_ref() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    facade = _facade(connection, media_store=_MediaStore())

    with pytest.raises(DoctorProfilePhotoNotFoundError):
        await facade.get_doctor_photo(12)


@pytest.mark.asyncio
async def test_get_doctor_photo_recognizes_webp_content() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.webp"] = _WEBP_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.webp",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.get_doctor_photo(12)

    assert result is not None
    assert result.media_type == "image/webp"


@pytest.mark.asyncio
async def test_get_doctor_photo_maps_storage_failure_to_typed_error() -> None:
    store = _MediaStore()
    store.read_error = OSError("storage offline")
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfilePhotoStoreUnavailableError):
        await facade.get_doctor_photo(12)


@pytest.mark.asyncio
async def test_delete_doctor_photo_clears_ref_before_deleting_object() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.enc"] = _JPEG_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            ),
            _Result(),
        ]
    )
    facade = _facade(connection, media_store=store)

    assert await facade.delete_doctor_photo(12) is None

    locked_delete = connection.execute.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(locked_delete)
    update = connection.execute.await_args_list[1].args[0]
    assert update.table.name == "partner_profiles"
    assert update._values["photo_ref"].value is None
    assert store.deleted == ["doctor/12/photo.enc"]
