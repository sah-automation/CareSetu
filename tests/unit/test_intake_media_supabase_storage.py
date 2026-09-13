"""Ticket #385: Supabase Storage intake-media backend (config-switched store).

Exercises the ``SupabaseStorageIntakeMediaStore`` concrete adapter against an
``httpx.MockTransport`` fake network (never real HTTP - same pattern as the
AI-gateway tests) and the ``build_media_store`` factory. Pins the port's
observable contract (#385 testing decisions):

- save posts ONLY ciphertext (nonce + AES-GCM output) with the bucket in the
  path and returns the opaque ``intake/<patient_id>/<uuid>.enc`` key.
- read of that key round-trips the original plaintext bytes.
- save non-2xx raises OSError; read 404 raises FileNotFoundError; 5xx raises
  OSError; network errors raise OSError (all retriable by the facade ladder).
- read of tampered ciphertext raises InvalidTag (not OSError).
- the facade's existing 3-attempt retry ladder wraps OSError unchanged.
- the factory selects local vs supabase, and supabase is fail-fast: missing
  URL/service-role key raises ValueError.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.adapters.media_store import (
    MEDIA_BUCKET,
    PREFIX,
    LocalFilesystemIntakeMediaStore,
    SupabaseStorageIntakeMediaStore,
    build_media_store,
)
from modules.intake.domain.exceptions import MediaTransferError
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import MediaFile

_FAKE_URL = "https://abc.supabase.co"
_FAKE_ROLE_KEY = "test-service-role-key"


def _storage_response(status_code: int, request: httpx.Request) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=request)


def _ok_response(request: httpx.Request) -> httpx.Response:
    return _storage_response(200, request)


def _store(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    key_bytes: bytes | None = None,
) -> SupabaseStorageIntakeMediaStore:
    """Build a store backed by a fake network (never real HTTP)."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseStorageIntakeMediaStore(
        supabase_url=_FAKE_URL,
        service_role_key=_FAKE_ROLE_KEY,
        client=client,
        key_bytes=key_bytes,
    )


def _memory_store(
    *,
    key_bytes: bytes | None = None,
) -> tuple[SupabaseStorageIntakeMediaStore, dict[str, bytes]]:
    """An in-memory fake where upload stores bytes and download serves them."""
    objects: dict[str, bytes] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        object_key = request.url.path.split(f"/storage/v1/object/{MEDIA_BUCKET}/", 1)[1]
        if request.method == "POST":
            objects[object_key] = request.content
            return httpx.Response(200, request=request)
        if request.method == "GET":
            content = objects.get(object_key)
            if content is None:
                return httpx.Response(404, request=request)
            return httpx.Response(200, content=content, request=request)
        return httpx.Response(405, request=request)

    return _store(_handler, key_bytes=key_bytes), objects


# ---------------------------------------------------------------------------
# facade harness (same shapes as test_intake_media_rerecord.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(
        self,
        scalar: object | None = None,
        row: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows


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
    store: object | None = None,
    sleep: _FakeSleep | None = None,
) -> IntakeFacade:
    return IntakeFacade(
        engine=_engine(connection),
        media_store=store,
        sleep=sleep or _FakeSleep(),
    )


def _media_file() -> MediaFile:
    return MediaFile(
        data=b"\x00" * 512,
        filename="recording.webm",
        media_type="audio",
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _intake_row(*, patient_id: int = 7) -> object:
    return SimpleNamespace(
        id=1,
        patient_id=patient_id,
        mode="voice",
        language="en",
        status="captured",
        record_attempts=1,
        text=None,
        transcript=None,
        transcript_usability=None,
        forced_text=False,
    )


def _media_row() -> object:
    return SimpleNamespace(
        id=11,
        intake_id=1,
        media_type="audio",
        object_key="intake/7/clip-1.enc",
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _playback_results() -> list[object]:
    # select(intake) -> select(media refs)
    return [
        _FakeResult(row=_intake_row()),
        _FakeResult(row=_media_row()),
    ]


# ---------------------------------------------------------------------------
# save: round-trip contract
# ---------------------------------------------------------------------------


async def test_save_returns_opaque_key_and_posts_only_ciphertext() -> None:
    """save returns an opaque intake/ key; the request body is ciphertext only."""
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, request=request)

    store = _store(_handler)
    data = b"plaintext-audio-never-leaves-the-app-" * 32

    object_key = await store.save(data=data, patient_id=7)

    # Key shape: intake/<patient_id>/<hex>.enc
    assert object_key.startswith(f"{PREFIX}/7/")
    assert object_key.endswith(".enc")
    assert len(object_key.split("/")) == 3

    # Exactly one POST, to the right bucket + path, with the service-role key.
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == f"/storage/v1/object/{MEDIA_BUCKET}/{object_key}"
    assert request.headers["authorization"] == f"Bearer {_FAKE_ROLE_KEY}"

    body = request.content
    # Payload is nonce(12) + AES-GCM ciphertext (plaintext + 16-byte tag), so
    # its length is fixed and the plaintext never appears in the body.
    assert len(body) == 12 + len(data) + 16
    assert data not in body


async def test_save_objects_are_not_overwritten() -> None:
    """Two saves for the same patient produce different object keys."""
    store, objects = _memory_store()
    data = b"audio" * 256

    key1 = await store.save(data=data, patient_id=7)
    key2 = await store.save(data=data, patient_id=7)

    assert key1 != key2
    assert objects[key1] != objects[key2]  # different nonces


# ---------------------------------------------------------------------------
# read: round-trip contract
# ---------------------------------------------------------------------------


async def test_read_round_trips_decrypted_bytes() -> None:
    """A key written by save is read back as the original plaintext."""
    store, objects = _memory_store()
    data = bytes(range(256)) * 16

    object_key = await store.save(data=data, patient_id=7)
    assert object_key in objects

    restored = await store.read(object_key=object_key)
    assert restored == data


# ---------------------------------------------------------------------------
# save: non-2xx raises OSError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_save_non_2xx_raises_oserror(status: int) -> None:
    store = _store(lambda request: _storage_response(status, request))

    with pytest.raises(OSError):
        await store.save(data=b"x" * 512, patient_id=7)


async def test_save_network_error_raises_oserror() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    store = _store(_handler)
    with pytest.raises(OSError):
        await store.save(data=b"x", patient_id=7)


# ---------------------------------------------------------------------------
# save: facade retry ladder wraps OSError unchanged
# ---------------------------------------------------------------------------


async def test_save_fails_facade_wraps_after_three_attempts() -> None:
    """Non-2xx on save → OSError → facade retries 3x → MediaTransferError."""
    store = _store(lambda request: _storage_response(500, request))
    sleep = _FakeSleep()
    facade = _facade(_connection([]), store=store, sleep=sleep)

    with pytest.raises(MediaTransferError, match="failed after 3 attempts"):
        await facade.upload_intake_media(patient_id=7, file=_media_file())

    assert len(sleep.waits) == 2
    assert sleep.waits == [0.5, 1.0]


# ---------------------------------------------------------------------------
# read: error taxonomy
# ---------------------------------------------------------------------------


async def test_read_missing_object_raises_file_not_found() -> None:
    store = _store(lambda request: _storage_response(404, request))

    with pytest.raises(FileNotFoundError):
        await store.read(object_key="intake/7/01ab.enc")


async def test_read_5xx_raises_oserror() -> None:
    store = _store(lambda request: _storage_response(503, request))

    with pytest.raises(OSError):
        await store.read(object_key="intake/7/01ab.enc")


async def test_read_network_error_raises_oserror() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    store = _store(_handler)
    with pytest.raises(OSError):
        await store.read(object_key="intake/7/01ab.enc")


async def test_read_outside_intake_prefix_raises_oserror() -> None:
    """Keys outside intake/ are refused even on read - URL injection safety."""
    store = _store(_ok_response)
    with pytest.raises(OSError, match="object key is outside the intake/ prefix"):
        await store.read(object_key="partner/7/secret.enc")


# ---------------------------------------------------------------------------
# read: tampered ciphertext → InvalidTag (not OSError)
# ---------------------------------------------------------------------------


async def test_read_tampered_ciphertext_raises_invalid_tag() -> None:
    """Ciphertext that fails the GCM tag check is InvalidTag, not OSError."""
    payload = b"not-a-real-nonce+ciphertext-need-at-least-28-bytes-for-tag" * 2
    store = _store(lambda request: httpx.Response(200, content=payload, request=request))

    with pytest.raises(InvalidTag):
        await store.read(object_key="intake/7/01ab.enc")


async def test_read_tampered_ciphertext_facade_wraps_unchanged() -> None:
    """The facade wraps InvalidTag from the store in MediaTransferError."""
    payload = b"not-a-real-nonce+ciphertext-need-at-least-28-bytes-for-tag" * 2
    store = _store(lambda request: httpx.Response(200, content=payload, request=request))
    facade = _facade(_connection(_playback_results()), store=store)

    with pytest.raises(MediaTransferError, match="failed to read media ref 11"):
        await facade.get_intake_media(
            intake_id=1,
            media_ref_id=11,
            caller_id=7,
            caller_role="patient",
        )


# ---------------------------------------------------------------------------
# build_media_store factory
# ---------------------------------------------------------------------------


def test_build_media_store_default_backend_is_local() -> None:
    store = build_media_store("var/intake-media", "")

    assert isinstance(store, LocalFilesystemIntakeMediaStore)


def test_build_media_store_local_returns_local_store() -> None:
    store = build_media_store("var/intake-media", "", backend="local")

    assert isinstance(store, LocalFilesystemIntakeMediaStore)


def test_build_media_store_supabase_returns_remote_store() -> None:
    store = build_media_store(
        "var/intake-media",
        "",
        backend="supabase",
        supabase_url="https://abc.supabase.co",
        supabase_service_role_key="sb-test",
    )

    assert isinstance(store, SupabaseStorageIntakeMediaStore)


def test_build_media_store_supabase_missing_creds_fails_fast() -> None:
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        build_media_store("var/intake-media", "", backend="supabase")

    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        build_media_store(
            "var/intake-media",
            "",
            backend="supabase",
            supabase_url="https://abc.supabase.co",
        )
