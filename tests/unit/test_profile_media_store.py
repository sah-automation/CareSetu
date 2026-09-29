"""Ticket #532 (ADR-0020): profile-media storage adapter (private profile photos).

Exercises the ``ProfileMediaStore`` port across its two concrete backends - the
local filesystem store and the ``SupabaseStorageProfileMediaStore`` against an
``httpx.MockTransport`` fake network (never real HTTP, same pattern as the
intake-media and AI-gateway tests) - plus the ``build_profile_media_store``
factory and the ``modules.profile_media.facade`` seam. Pins the port's
observable contract:

- save posts ONLY ciphertext (nonce + AES-GCM output) to the private
  ``profile-media`` bucket with a service-role bearer and returns the opaque
  ``patient/<user_id>/<uuid>.enc`` key; the doctor prefix files under
  ``doctor/<partner_id>/<uuid>.enc``.
- read of that key round-trips the original plaintext bytes; delete removes the
  object (and the local file), so a removed photo is never orphaned.
- save of a key prefix outside the ``patient/``/``doctor/`` namespace is refused
  (defense-in-depth: nothing files under a prefix the read path would reject);
  read/delete of such a key is refused too.
- save non-2xx raises OSError; read/delete 404 raises FileNotFoundError; 5xx and
  network errors raise OSError (all retriable by the caller ladder).
- read of tampered ciphertext raises InvalidTag (not OSError).
- the factory selects local vs supabase, and supabase is fail-fast: missing
  URL/service-role key raises ValueError.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from modules.profile_media import facade as profile_media_facade
from modules.profile_media.adapters.media_store import (
    DOCTOR_PREFIX,
    MEDIA_BUCKET,
    PATIENT_PREFIX,
    LocalFilesystemProfileMediaStore,
    ProfileMediaRetryPolicy,
    ProfileMediaStore,
    ProfileMediaStoreError,
    ResilientProfileMediaStore,
    SupabaseStorageProfileMediaStore,
    build_profile_media_store,
)
from modules.profile_media.facade import (
    build_profile_media_store as build_via_facade,
)

_FAKE_URL = "https://abc.supabase.co"
_FAKE_ROLE_KEY = "test-service-role-key"


def _retry_policy(
    *,
    max_attempts: int = 2,
    backoff_seconds: float = 0.25,
    circuit_breaker_threshold: int = 2,
    circuit_breaker_cooldown_seconds: float = 10.0,
) -> ProfileMediaRetryPolicy:
    return ProfileMediaRetryPolicy(
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        jitter_fraction=0.0,
        circuit_breaker_threshold=circuit_breaker_threshold,
        circuit_breaker_cooldown_seconds=circuit_breaker_cooldown_seconds,
    )


def _storage_response(status_code: int, request: httpx.Request) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=request)


def _ok_response(request: httpx.Request) -> httpx.Response:
    return _storage_response(200, request)


def _store(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    key_bytes: bytes | None = None,
) -> SupabaseStorageProfileMediaStore:
    """Build a store backed by a fake network (never real HTTP)."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseStorageProfileMediaStore(
        supabase_url=_FAKE_URL,
        service_role_key=_FAKE_ROLE_KEY,
        client=client,
        key_bytes=key_bytes,
        timeout_seconds=30.0,
    )


def _memory_store(
    *,
    key_bytes: bytes | None = None,
) -> tuple[SupabaseStorageProfileMediaStore, dict[str, bytes]]:
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
        if request.method == "DELETE":
            if object_key not in objects:
                return httpx.Response(404, request=request)
            del objects[object_key]
            return httpx.Response(200, request=request)
        return httpx.Response(405, request=request)

    return _store(_handler, key_bytes=key_bytes), objects


# ---------------------------------------------------------------------------
# save: key layout + round-trip contract
# ---------------------------------------------------------------------------


async def test_save_patient_prefix_returns_opaque_key_and_posts_only_ciphertext() -> None:
    """save returns an opaque patient/ key; the request body is ciphertext only."""
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, request=request)

    store = _store(_handler)
    data = b"plaintext-photo-never-leaves-the-app-" * 32

    object_key = await store.save(data=data, subject_id=7)

    # Key shape: patient/<patient_id>/<hex>.enc
    assert object_key.startswith(f"{PATIENT_PREFIX}/7/")
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
    data = b"photo" * 256

    key1 = await store.save(data=data, subject_id=7)
    key2 = await store.save(data=data, subject_id=7)

    assert key1 != key2
    assert objects[key1] != objects[key2]  # different nonces


# ---------------------------------------------------------------------------
# save/read/delete: doctor prefix
# ---------------------------------------------------------------------------


async def test_save_doctor_prefix_files_under_the_doctor_namespace() -> None:
    """A doctor-scoped save files under doctor/<partner_id>/<uuid>.enc."""
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, request=request)

    store = _store(_handler)

    object_key = await store.save(data=b"doctor-photo", subject_id=12, prefix=DOCTOR_PREFIX)

    assert object_key.startswith(f"{DOCTOR_PREFIX}/12/")
    assert object_key.endswith(".enc")
    assert len(object_key.split("/")) == 3
    request = captured[0]
    assert request.url.path == f"/storage/v1/object/{MEDIA_BUCKET}/{object_key}"


async def test_save_outside_supported_prefix_is_refused_without_a_request() -> None:
    """A save under a prefix outside patient/ doctor/ fails before any upload."""

    def _handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be made for a refused prefix")

    store = _store(_handler)

    with pytest.raises(OSError, match="prefix is outside the supported prefixes"):
        await store.save(data=b"photo", subject_id=7, prefix="rx_input")


async def test_doctor_prefix_round_trips_on_read() -> None:
    """A doctor/ object reads back as its original plaintext."""
    store, objects = _memory_store()
    data = b"doctor-photo-bytes-" * 16

    object_key = await store.save(data=data, subject_id=12, prefix=DOCTOR_PREFIX)
    restored = await store.read(object_key=object_key)

    assert object_key in objects
    assert restored == data


# ---------------------------------------------------------------------------
# read: round-trip contract
# ---------------------------------------------------------------------------


async def test_read_round_trips_decrypted_bytes() -> None:
    """A key written by save is read back as the original plaintext."""
    store, objects = _memory_store()
    data = bytes(range(256)) * 16

    object_key = await store.save(data=data, subject_id=7)
    assert object_key in objects

    restored = await store.read(object_key=object_key)
    assert restored == data


# ---------------------------------------------------------------------------
# delete: object removed, not orphaned
# ---------------------------------------------------------------------------


async def test_delete_removes_the_object() -> None:
    """delete removes the ciphertext so a removed photo is not orphaned."""
    store, objects = _memory_store()
    object_key = await store.save(data=b"photo-to-remove", subject_id=7)
    assert object_key in objects

    await store.delete(object_key=object_key)

    assert object_key not in objects
    with pytest.raises(FileNotFoundError):
        await store.read(object_key=object_key)


async def test_delete_of_unknown_object_raises_file_not_found() -> None:
    store = _store(lambda request: _storage_response(404, request))

    with pytest.raises(FileNotFoundError):
        await store.delete(object_key="patient/7/01ab.enc")


# ---------------------------------------------------------------------------
# save: non-2xx raises OSError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_save_non_2xx_raises_oserror(status: int) -> None:
    store = _store(lambda request: _storage_response(status, request))

    with pytest.raises(ProfileMediaStoreError) as raised:
        await store.save(data=b"x" * 512, subject_id=7)

    assert raised.value.retryable is (status >= 500)
    assert raised.value.status_code == status


async def test_save_network_error_raises_oserror() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    store = _store(_handler)
    with pytest.raises(ProfileMediaStoreError) as raised:
        await store.save(data=b"x", subject_id=7)

    assert raised.value.retryable is True


# ---------------------------------------------------------------------------
# read/delete: error taxonomy
# ---------------------------------------------------------------------------


async def test_read_missing_object_raises_file_not_found() -> None:
    store = _store(lambda request: _storage_response(404, request))

    with pytest.raises(FileNotFoundError):
        await store.read(object_key="patient/7/01ab.enc")


async def test_read_5xx_raises_oserror() -> None:
    store = _store(lambda request: _storage_response(503, request))

    with pytest.raises(ProfileMediaStoreError) as raised:
        await store.read(object_key="patient/7/01ab.enc")

    assert raised.value.retryable is True
    assert raised.value.status_code == 503


async def test_read_network_error_raises_oserror() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    store = _store(_handler)
    with pytest.raises(ProfileMediaStoreError) as raised:
        await store.read(object_key="patient/7/01ab.enc")

    assert raised.value.retryable is True


async def test_read_outside_supported_prefix_raises_oserror() -> None:
    """Keys outside patient/ and doctor/ are refused even on read."""
    store = _store(_ok_response)
    with pytest.raises(OSError, match="object key is outside the supported prefixes"):
        await store.read(object_key="intake/7/secret.enc")
    with pytest.raises(OSError, match="object key is outside the supported prefixes"):
        await store.read(object_key="doctor/7/1/extra.enc")


async def test_delete_outside_supported_prefix_raises_oserror() -> None:
    """Keys outside patient/ and doctor/ are refused on delete too."""
    store = _store(_ok_response)
    with pytest.raises(OSError, match="object key is outside the supported prefixes"):
        await store.delete(object_key="partner/7/secret.enc")


# ---------------------------------------------------------------------------
# read: tampered ciphertext → InvalidTag (not OSError)
# ---------------------------------------------------------------------------


async def test_read_tampered_ciphertext_raises_invalid_tag() -> None:
    """Ciphertext that fails the GCM tag check is InvalidTag, not OSError."""
    payload = b"not-a-real-nonce+ciphertext-need-at-least-28-bytes-for-tag" * 2
    store = _store(lambda request: httpx.Response(200, content=payload, request=request))

    with pytest.raises(InvalidTag):
        await store.read(object_key="patient/7/01ab.enc")


async def test_resilient_store_retries_transient_upload_at_the_same_object_key() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = 503 if len(requests) == 1 else 200
        return httpx.Response(status, request=request)

    sleep = AsyncMock()
    store = ResilientProfileMediaStore(
        _store(_handler),
        _retry_policy(max_attempts=3),
        sleep=sleep,
        monotonic_clock=lambda: 0.0,
        random_value=lambda: 0.0,
    )

    object_key = await store.save(data=b"photo", subject_id=12, prefix=DOCTOR_PREFIX)

    assert len(requests) == 2
    assert requests[0].url.path == requests[1].url.path
    assert object_key in requests[0].url.path
    assert sleep.await_args.args[0] == 0.25


async def test_resilient_store_does_not_retry_non_transient_upload() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, request=request)

    sleep = AsyncMock()
    store = ResilientProfileMediaStore(
        _store(_handler),
        _retry_policy(),
        sleep=sleep,
        monotonic_clock=lambda: 0.0,
        random_value=lambda: 0.0,
    )

    with pytest.raises(ProfileMediaStoreError) as raised:
        await store.save(data=b"photo", subject_id=12, prefix=DOCTOR_PREFIX)

    assert raised.value.retryable is False
    assert raised.value.retries_exhausted is False
    assert len(requests) == 1
    sleep.assert_not_awaited()


async def test_resilient_store_applies_retry_and_circuit_to_read() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    store = ResilientProfileMediaStore(
        _store(_handler),
        _retry_policy(circuit_breaker_threshold=1),
        sleep=AsyncMock(),
        monotonic_clock=lambda: 0.0,
        random_value=lambda: 0.0,
    )

    with pytest.raises(ProfileMediaStoreError) as exhausted:
        await store.read(object_key="doctor/12/photo.enc")
    with pytest.raises(ProfileMediaStoreError) as opened:
        await store.read(object_key="doctor/12/photo.enc")

    assert exhausted.value.retries_exhausted is True
    assert opened.value.circuit_open is True
    assert len(requests) == 2


async def test_resilient_store_applies_retry_and_circuit_to_delete() -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    store = ResilientProfileMediaStore(
        _store(_handler),
        _retry_policy(circuit_breaker_threshold=1),
        sleep=AsyncMock(),
        monotonic_clock=lambda: 0.0,
        random_value=lambda: 0.0,
    )

    with pytest.raises(ProfileMediaStoreError):
        await store.delete(object_key="doctor/12/photo.enc")
    with pytest.raises(ProfileMediaStoreError) as opened:
        await store.delete(object_key="doctor/12/photo.enc")

    assert opened.value.circuit_open is True
    assert len(requests) == 2


# ---------------------------------------------------------------------------
# local backend: key layout, durable persistence, delete
# ---------------------------------------------------------------------------


async def test_local_store_round_trips_and_files_under_prefix(tmp_path: Path) -> None:
    """The local backend files ciphertext and reads it back as plaintext."""
    store = LocalFilesystemProfileMediaStore(root=tmp_path)

    object_key = await store.save(data=b"avatar.png", subject_id=7)

    assert object_key.startswith(f"{PATIENT_PREFIX}/7/")
    assert len(object_key.split("/")) == 3
    assert (tmp_path / object_key).is_file()
    assert await store.read(object_key=object_key) == b"avatar.png"


async def test_local_store_doctor_prefix(tmp_path: Path) -> None:
    store = LocalFilesystemProfileMediaStore(root=tmp_path)

    object_key = await store.save(data=b"doctor-avatar", subject_id=12, prefix=DOCTOR_PREFIX)
    assert object_key.startswith(f"{DOCTOR_PREFIX}/12/")
    assert await store.read(object_key=object_key) == b"doctor-avatar"


async def test_local_store_persists_across_store_instances(tmp_path: Path) -> None:
    """Ciphertext written by one store decrypts in a fresh store with the same key."""
    key = b"k" * 32
    first = LocalFilesystemProfileMediaStore(root=tmp_path, key_bytes=key)
    object_key = await first.save(data=b"durable-photo", subject_id=7)

    second = LocalFilesystemProfileMediaStore(root=tmp_path, key_bytes=key)
    assert await second.read(object_key=object_key) == b"durable-photo"


async def test_local_store_delete_removes_the_file(tmp_path: Path) -> None:
    store = LocalFilesystemProfileMediaStore(root=tmp_path)
    object_key = await store.save(data=b"photo-to-remove", subject_id=7)

    await store.delete(object_key=object_key)

    assert not (tmp_path / object_key).exists()
    with pytest.raises(OSError):
        await store.read(object_key=object_key)


async def test_local_store_read_outside_supported_prefix_raises_oserror(tmp_path: Path) -> None:
    store = LocalFilesystemProfileMediaStore(root=tmp_path)

    with pytest.raises(OSError, match="object key is outside the supported prefixes"):
        await store.read(object_key="rx_input/7/seed.enc")


async def test_local_store_save_outside_supported_prefix_writes_nothing(tmp_path: Path) -> None:
    """A save under a traversal prefix is refused and files nothing under root."""
    store = LocalFilesystemProfileMediaStore(root=tmp_path)

    with pytest.raises(OSError, match="prefix is outside the supported prefixes"):
        await store.save(data=b"photo", subject_id=7, prefix="../escape")

    assert list(tmp_path.iterdir()) == []


def test_local_store_refuses_non_32_byte_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="32-byte"):
        LocalFilesystemProfileMediaStore(root=tmp_path, key_bytes=b"too-short")


# ---------------------------------------------------------------------------
# decode_key + factory
# ---------------------------------------------------------------------------


def test_decode_key_rejects_malformed_base64() -> None:
    from modules.profile_media.adapters.media_store import decode_key

    with pytest.raises(ValueError, match="PROFILE_MEDIA_KEY is not valid base64"):
        decode_key("not base64!!!")


def test_facade_seam_exposes_the_port_factory_and_prefixes(tmp_path: Path) -> None:
    """The facade seam re-exports the port + factory + prefix constants only.

    Cross-module callers (iam/partner) program against the port and pass a role
    prefix; the concrete backends stay under ``adapters/`` so a caller cannot
    pick a backend itself.
    """
    assert ProfileMediaStore.__name__ in dir(profile_media_facade)
    assert build_profile_media_store.__name__ in dir(profile_media_facade)

    store = build_via_facade(str(tmp_path), "")
    assert isinstance(store, LocalFilesystemProfileMediaStore)
    assert "PATIENT_PREFIX" in dir(profile_media_facade)
    assert "DOCTOR_PREFIX" in dir(profile_media_facade)
    assert "ProfileMediaStoreError" in dir(profile_media_facade)


def test_build_default_backend_is_local() -> None:
    store = build_profile_media_store("var/profile-media", "")

    assert isinstance(store, LocalFilesystemProfileMediaStore)


def test_build_local_returns_local_store() -> None:
    store = build_profile_media_store("var/profile-media", "", backend="local")

    assert isinstance(store, LocalFilesystemProfileMediaStore)


def test_build_supabase_returns_remote_store() -> None:
    store = build_profile_media_store(
        "var/profile-media",
        "",
        backend="supabase",
        supabase_url="https://abc.supabase.co",
        supabase_service_role_key="sb-test",
        retry_policy=_retry_policy(),
        timeout_seconds=30.0,
    )

    assert isinstance(store, ResilientProfileMediaStore)


def test_build_supabase_missing_creds_fails_fast() -> None:
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        build_profile_media_store("var/profile-media", "", backend="supabase")

    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        build_profile_media_store(
            "var/profile-media",
            "",
            backend="supabase",
            supabase_url="https://abc.supabase.co",
        )


# ---------------------------------------------------------------------------
# port shape: everything a caller route needs is on the protocol
# ---------------------------------------------------------------------------


def test_port_surface(tmp_path: Path) -> None:
    """The profile-media port keeps the save/read/delete/close shape."""
    store: ProfileMediaStore = LocalFilesystemProfileMediaStore(root=tmp_path)
    assert callable(store.save)
    assert callable(store.read)
    assert callable(store.delete)
    assert callable(store.close)
