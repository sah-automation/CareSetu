"""US-20 (#533): profile-photo facade contract at the facade-with-fakes seam.

Drives the real ``IdentityFacade`` photo methods (``save_patient_photo`` /
``get_patient_photo`` / ``delete_patient_photo``) with a fake engine, a
controllable fake ``ProfileMediaStore``, and an injected fake backoff sleep -
the same facade-with-fakes pattern the intake media suite (``test_intake_media_rerecord.py``)
uses. Pins the durable contract the route tests only stub:

- upload validates the photo contract before any store or DB work (GIF and
  oversized uploads are refused with zero store writes),
- the store write rides the 3-attempt backoff ladder (NFR-PERF-002) and then
  raises :class:`ProfilePhotoTransferError` - a failed upload is never silent,
- a failed ref-persistence rolls the freshly filed object back so the store is
  not orphaned; replace retires the superseded object,
- reads stream the stored bytes with the sniffed content type, and a dangling
  key is "no photo", never a 500,
- removal clears the ref first (rowcount-based), then retires the object, and
  is idempotent; every operation is scoped to ``identity_id``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.domain.exceptions import (
    IamError,
    PatientProfileNotSetError,
    ProfilePhotoTransferError,
    ProfilePhotoValidationError,
)
from modules.iam.identity_facade import (
    MAX_PROFILE_PHOTO_ATTEMPTS,
    MAX_PROFILE_PHOTO_BYTES,
    IdentityFacade,
)

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _profile_row(*, photo_ref: str | None = "patient/1/photo-1.jpg") -> dict[str, object]:
    return {
        "name": "Asha Devi",
        "age": 34,
        "gender": "female",
        "preferred_language": "hi",
        "area": "Daltonganj",
        "emergency_contact": "+9199876543211",
        "photo_ref": photo_ref,
    }


class _FakeResult:
    """Mimics ``Select``/``Update`` result shapes: ``mappings().first()`` + ``rowcount``."""

    def __init__(self, *, row: dict[str, object] | None = None, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    def mappings(self) -> _FakeResult:
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _FakeMediaStore:
    """Controllable ``ProfileMediaStore``: fails the first ``n_failures`` saves.

    Mints a fresh monotonic key per successful save (the real store's behavior),
    so a replace always produces a distinct ref that retires the old one.
    """

    def __init__(self, *, n_failures: int = 0, fail_reads: bool = False) -> None:
        self.n_failures = n_failures
        self.fail_reads = fail_reads
        self.save_calls = 0
        self._counter = 0
        self.captured: list[tuple[bytes, int, str]] = []
        self.deleted: list[str] = []
        self.read_keys: list[str] = []
        self.stored: dict[str, bytes] = {}

    async def save(self, *, data: bytes, subject_id: int, prefix: str) -> str:
        self.save_calls += 1
        self.captured.append((data, subject_id, prefix))
        if self.save_calls <= self.n_failures:
            raise OSError("disk full")
        self._counter += 1
        key = f"{prefix}/{subject_id}/photo-{self._counter}.jpg"
        self.stored[key] = data
        return key

    async def read(self, *, object_key: str) -> bytes:
        self.read_keys.append(object_key)
        if self.fail_reads:
            raise FileNotFoundError(object_key)
        return self.stored[object_key]

    async def delete(self, *, object_key: str) -> None:
        self.deleted.append(object_key)
        self.stored.pop(object_key, None)


class _FakeSleep:
    """Records backoff waits instead of actually sleeping."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(
    connection: AsyncMock,
    *,
    store: _FakeMediaStore | None = None,
    sleep: _FakeSleep | None = None,
) -> IdentityFacade:
    return IdentityFacade(
        _engine(connection),
        otp_sender=lambda phone, otp: None,
        media_store=store,
        sleep=sleep or _FakeSleep(),
    )


# ---------------------------------------------------------------------------
# PUT facade: save (with the resilience ladder)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_uploads_under_the_patient_prefix_and_persists_only_the_ref() -> None:
    store = _FakeMediaStore()
    connection = _connection(
        [
            _FakeResult(row=_profile_row()),  # profile read
            _FakeResult(rowcount=1),  # photo_ref update
        ]
    )
    sleep = _FakeSleep()
    facade = _facade(connection, store=store, sleep=sleep)

    profile = await facade.save_patient_photo(
        identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg"
    )

    assert profile.photo_ref == "patient/1/photo-1.jpg"
    assert store.captured == [(_JPEG_BYTES, 1, "patient")]
    assert store.save_calls == 1
    assert sleep.waits == []


@pytest.mark.asyncio
async def test_save_rides_the_retry_ladder_when_the_store_is_flaky() -> None:
    store = _FakeMediaStore(n_failures=1)
    connection = _connection(
        [
            _FakeResult(row=_profile_row()),
            _FakeResult(rowcount=1),
        ]
    )
    sleep = _FakeSleep()
    facade = _facade(connection, store=store, sleep=sleep)

    profile = await facade.save_patient_photo(
        identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg"
    )

    assert store.save_calls == 2
    assert sleep.waits == [0.5]
    assert profile.photo_ref == "patient/1/photo-1.jpg"


@pytest.mark.asyncio
async def test_save_exhausted_ladder_raises_the_typed_error_without_persisting() -> None:
    store = _FakeMediaStore(n_failures=99)
    connection = _connection([_FakeResult(row=_profile_row())])
    sleep = _FakeSleep()
    facade = _facade(connection, store=store, sleep=sleep)

    with pytest.raises(ProfilePhotoTransferError):
        await facade.save_patient_photo(identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg")

    assert store.save_calls == MAX_PROFILE_PHOTO_ATTEMPTS
    assert sleep.waits == [0.5, 1.0]
    # Only the profile read ran - the photo_ref update never executed.
    assert connection.execute.await_count == 1


@pytest.mark.asyncio
async def test_save_rejects_gif_before_touching_store_or_database() -> None:
    store = _FakeMediaStore()
    connection = _connection([])
    facade = _facade(connection, store=store)

    with pytest.raises(ProfilePhotoValidationError):
        await facade.save_patient_photo(identity_id=1, data=_JPEG_BYTES, media_type="image/gif")

    assert store.save_calls == 0
    connection.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_rejects_oversized_photo_before_touching_store_or_database() -> None:
    store = _FakeMediaStore()
    connection = _connection([])
    facade = _facade(connection, store=store)

    with pytest.raises(ProfilePhotoValidationError):
        await facade.save_patient_photo(
            identity_id=1,
            data=b"\x00" * (MAX_PROFILE_PHOTO_BYTES + 1),
            media_type="image/png",
        )

    assert store.save_calls == 0
    connection.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_requires_an_existing_profile_row() -> None:
    store = _FakeMediaStore()
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection, store=store)

    with pytest.raises(PatientProfileNotSetError):
        await facade.save_patient_photo(identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg")

    assert store.save_calls == 0


@pytest.mark.asyncio
async def test_save_replace_retires_the_superseded_object() -> None:
    store = _FakeMediaStore()
    connection = _connection(
        [
            _FakeResult(row=_profile_row(photo_ref="patient/1/photo-old.jpg")),
            _FakeResult(rowcount=1),
        ]
    )
    facade = _facade(connection, store=store)

    profile = await facade.save_patient_photo(
        identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg"
    )

    assert profile.photo_ref == "patient/1/photo-1.jpg"
    assert store.deleted == ["patient/1/photo-old.jpg"]
    assert store.stored["patient/1/photo-1.jpg"] == _JPEG_BYTES


@pytest.mark.asyncio
async def test_save_ref_persistence_failure_rolls_back_the_fresh_object() -> None:
    store = _FakeMediaStore()
    connection = _connection(
        [
            _FakeResult(row=_profile_row(photo_ref="patient/1/photo-old.jpg")),
            RuntimeError("database connection dropped"),
        ]
    )
    facade = _facade(connection, store=store)

    with pytest.raises(RuntimeError):
        await facade.save_patient_photo(identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg")

    # The freshly filed object is cleaned up so the store is not orphaned.
    assert store.deleted == ["patient/1/photo-1.jpg"]


# ---------------------------------------------------------------------------
# GET facade: stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_streams_stored_bytes_with_the_sniffed_content_type() -> None:
    store = _FakeMediaStore()
    store.stored["patient/1/photo-1.jpg"] = _JPEG_BYTES
    connection = _connection([_FakeResult(row=_profile_row(photo_ref="patient/1/photo-1.jpg"))])
    facade = _facade(connection, store=store)

    photo = await facade.get_patient_photo(identity_id=1)

    assert photo is not None
    assert photo.data == _JPEG_BYTES
    assert photo.media_type == "image/jpeg"
    assert store.read_keys == ["patient/1/photo-1.jpg"]


@pytest.mark.asyncio
async def test_get_without_a_photo_is_none_without_a_store_read() -> None:
    store = _FakeMediaStore()
    connection = _connection([_FakeResult(row=_profile_row(photo_ref=None))])
    facade = _facade(connection, store=store)

    photo = await facade.get_patient_photo(identity_id=1)

    assert photo is None
    assert store.read_keys == []


@pytest.mark.asyncio
async def test_get_dangling_key_is_none_not_an_error() -> None:
    store = _FakeMediaStore(fail_reads=True)
    connection = _connection([_FakeResult(row=_profile_row(photo_ref="patient/1/photo-1.jpg"))])
    facade = _facade(connection, store=store)

    photo = await facade.get_patient_photo(identity_id=1)

    assert photo is None


# ---------------------------------------------------------------------------
# DELETE facade: remove
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_clears_the_ref_then_retires_the_object() -> None:
    store = _FakeMediaStore()
    store.stored["patient/1/photo-1.jpg"] = _JPEG_BYTES
    connection = _connection(
        [
            _FakeResult(row=_profile_row(photo_ref="patient/1/photo-1.jpg")),
            _FakeResult(rowcount=1),  # photo_ref -> NULL
        ]
    )
    facade = _facade(connection, store=store)

    profile = await facade.delete_patient_photo(identity_id=1)

    assert profile.photo_ref is None
    assert store.deleted == ["patient/1/photo-1.jpg"]
    assert store.stored == {}
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_delete_is_idempotent_when_no_photo_is_set() -> None:
    store = _FakeMediaStore()
    connection = _connection([_FakeResult(row=_profile_row(photo_ref=None))])
    facade = _facade(connection, store=store)

    profile = await facade.delete_patient_photo(identity_id=1)

    assert profile.photo_ref is None
    assert store.deleted == []
    assert connection.execute.await_count == 1  # only the profile read


@pytest.mark.asyncio
async def test_delete_requires_an_existing_profile_row() -> None:
    store = _FakeMediaStore()
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection, store=store)

    with pytest.raises(PatientProfileNotSetError):
        await facade.delete_patient_photo(identity_id=1)

    assert store.deleted == []


# ---------------------------------------------------------------------------
# Unconfigured media store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_photo_ops_refuse_without_a_configured_media_store() -> None:
    connection = _connection([])
    facade = _facade(connection, store=None)

    with pytest.raises(IamError):
        await facade.save_patient_photo(identity_id=1, data=_JPEG_BYTES, media_type="image/jpeg")
    with pytest.raises(IamError):
        await facade.get_patient_photo(identity_id=1)
    with pytest.raises(IamError):
        await facade.delete_patient_photo(identity_id=1)

    connection.execute.assert_not_called()


# ---------------------------------------------------------------------------
# The returned profile is the caller's view (identity scoping)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_scopes_the_write_to_the_given_identity_id() -> None:
    store = _FakeMediaStore()
    connection = _connection(
        [
            _FakeResult(row=_profile_row(photo_ref="patient/2/photo-1.jpg")),
            _FakeResult(rowcount=1),
        ]
    )
    facade = _facade(connection, store=store)

    profile = await facade.save_patient_photo(
        identity_id=2, data=_PNG_BYTES, media_type="image/png"
    )

    assert store.captured == [(_PNG_BYTES, 2, "patient")]
    assert profile.photo_ref == "patient/2/photo-1.jpg"
    assert profile.name == "Asha Devi"
    assert profile.age == 34
