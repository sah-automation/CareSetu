"""Doctor-console/profiles batch, ticket #532 (ADR-0020): private profile-media store.

Profile photos are PII (security-phii-standards: a photo reliably identifies a
person, so it falls under the same at-rest encryption and refs-only-in-SQL rules
as intake audio). This adapter encrypts each photo with AES-256-GCM (the
``cryptography`` package - the only crypto dependency the cost floor ``NFR-001``
admits, same choice as the intake media and partner artifact stores) and answers
an opaque role-prefixed object key: ``patient/<user-id>/<uuid>.enc`` for the
patient profile photo and ``doctor/<user-id>/<uuid>.enc`` for the doctor profile
photo. Only a key is ever persisted on the ``iam``/``partner`` profile rows -
never the photo bytes and never the plaintext (ADR-0020 D2, refs only in SQL).

Two concrete backends sit behind the ``ProfileMediaStore`` port, selected by
``PROFILE_MEDIA_BACKEND`` and resolved by the :func:`build_profile_media_store`
factory:

- **local** (default): files the ciphertext under the repository ``var/`` root
  under ``patient/``/``doctor/``. Used by dev/CI/tests so nothing depends on
  the network.
- **supabase** (production): POSTs the ciphertext into the private
  ``profile-media`` Supabase Storage bucket via the
  ``/storage/v1/object/{bucket}/{object_key}`` REST API over
  ``httpx.AsyncClient`` with the service-role key. Service-role-writes-only
  (never client-writable) and the bucket is private with no public-read policies
  (ADR-0020 D1), so a leaked URL is not a leak. The provider only ever sees
  ciphertext - at-rest encryption stays owned by the app - and an ephemeral
  Render disk can never wipe a photo on redeploy.

The caller never touches bytes or the bucket: ``save`` hands a raw photo to the
store and gets back the key, reads stream through the backend (never a public
URL), and ``delete`` removes an owned photo on removal. This adapter is a thin
seam (coding-standards A-S3, adapter has no policy) - authorization (own photo
for the patient surface, consent-gated photos for the doctor surface) is the
caller facade's job.

The key is a base64 32-byte value from the environment (``PROFILE_MEDIA_KEY``),
required in production and never committed. For local-dev/test where no key is
configured, the store derives an ephemeral per-process key so the encrypted
write path is exercised (same convention as the intake media store).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import random
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TypeVar

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Object-storage prefix under which every patient profile photo is filed.
PATIENT_PREFIX: Final[str] = "patient"

#: Object-storage prefix under which every doctor profile photo is filed.
DOCTOR_PREFIX: Final[str] = "doctor"

#: The only object-storage prefixes this store admits for write/read/delete.
_SUPPORTED_PREFIXES: Final[frozenset[str]] = frozenset({PATIENT_PREFIX, DOCTOR_PREFIX})

#: Private Supabase Storage bucket holding the ciphertext (ADR-0020 D1). The
#: bucket is created private at provisioning with no public-read policies, so a
#: leaked object key is not a leak; reads stream through the backend only.
MEDIA_BUCKET: Final[str] = "profile-media"

_EXT = ".enc"

_STORAGE_OBJECT_ENDPOINT = "storage/v1/object"

logger = logging.getLogger(__name__)

_ResultT = TypeVar("_ResultT")


def _retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500


class ProfileMediaStoreError(OSError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retries_exhausted: bool = False,
        circuit_open: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retries_exhausted = retries_exhausted
        self.circuit_open = circuit_open


@dataclass(frozen=True)
class ProfileMediaRetryPolicy:
    max_attempts: int
    backoff_seconds: float
    jitter_fraction: float
    circuit_breaker_threshold: int
    circuit_breaker_cooldown_seconds: float

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not math.isfinite(self.backoff_seconds) or self.backoff_seconds <= 0:
            raise ValueError("backoff_seconds must be finite and positive")
        if not math.isfinite(self.jitter_fraction) or not 0 <= self.jitter_fraction < 1:
            raise ValueError("jitter_fraction must be finite and in [0, 1)")
        if self.circuit_breaker_threshold <= 0:
            raise ValueError("circuit_breaker_threshold must be positive")
        if (
            not math.isfinite(self.circuit_breaker_cooldown_seconds)
            or self.circuit_breaker_cooldown_seconds <= 0
        ):
            raise ValueError("circuit_breaker_cooldown_seconds must be finite and positive")


class _ProfileMediaCircuit:
    def __init__(
        self,
        policy: ProfileMediaRetryPolicy,
        monotonic_clock: Callable[[], float],
    ) -> None:
        self._policy = policy
        self._monotonic_clock = monotonic_clock
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def allow_request(self) -> bool:
        if self._state == "open":
            if self._monotonic_clock() - self._opened_at < (
                self._policy.circuit_breaker_cooldown_seconds
            ):
                return False
            self._state = "half_open"
        if self._state == "half_open":
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        if self._state == "half_open":
            logger.info("profile media circuit recovered")
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._probe_in_flight = False
        if self._state == "half_open":
            self._state = "open"
            self._opened_at = self._monotonic_clock()
            logger.warning("profile media circuit reopened")
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._policy.circuit_breaker_threshold:
            self._state = "open"
            self._opened_at = self._monotonic_clock()
            logger.warning(
                "profile media circuit opened failures=%d",
                self._consecutive_failures,
            )


class ResilientProfileMediaStore:
    def __init__(
        self,
        backend: ProfileMediaStore,
        policy: ProfileMediaRetryPolicy,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic_clock: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._backend = backend
        self._policy = policy
        self._sleep = sleep
        self._random_value = random_value
        self._circuit = _ProfileMediaCircuit(policy, monotonic_clock)

    async def _run(
        self,
        operation: str,
        call: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        if not self._circuit.allow_request():
            logger.warning("profile media circuit open operation=%s", operation)
            raise ProfileMediaStoreError(
                "profile media store circuit is open",
                retryable=False,
                circuit_open=True,
            )
        for attempt in range(1, self._policy.max_attempts + 1):
            if attempt > 1:
                exponential = self._policy.backoff_seconds * float(2 ** (attempt - 2))
                delay = exponential * (1.0 + self._policy.jitter_fraction * self._random_value())
                await self._sleep(delay)
            try:
                result = await call()
            except ProfileMediaStoreError as exc:
                if not exc.retryable:
                    logger.warning(
                        "profile media operation rejected operation=%s "
                        "status_code=%s error_type=%s",
                        operation,
                        exc.status_code,
                        type(exc).__name__,
                    )
                    self._circuit.record_success()
                    raise
                if attempt >= self._policy.max_attempts:
                    exc.retries_exhausted = True
                    self._circuit.record_failure()
                    logger.warning(
                        "profile media retry exhausted operation=%s attempts=%d",
                        operation,
                        attempt,
                    )
                    raise
                logger.warning(
                    "profile media retry operation=%s attempt=%d error_type=%s",
                    operation,
                    attempt,
                    type(exc).__name__,
                )
            except (FileNotFoundError, InvalidTag):
                self._circuit.record_success()
                raise
            else:
                self._circuit.record_success()
                return result
        raise ProfileMediaStoreError(
            "profile media operation exhausted unexpectedly",
            retryable=False,
        )

    async def save(
        self,
        *,
        data: bytes,
        subject_id: int,
        prefix: str = PATIENT_PREFIX,
        object_key: str | None = None,
    ) -> str:
        object_key = _resolve_save_object_key(
            object_key,
            prefix=prefix,
            subject_id=subject_id,
        )
        return await self._run(
            "save",
            lambda: self._backend.save(
                data=data,
                subject_id=subject_id,
                prefix=prefix,
                object_key=object_key,
            ),
        )

    async def read(self, *, object_key: str) -> bytes:
        return await self._run("read", lambda: self._backend.read(object_key=object_key))

    async def delete(self, *, object_key: str) -> None:
        try:
            await self._run("delete", lambda: self._backend.delete(object_key=object_key))
        except FileNotFoundError:
            return

    async def close(self) -> None:
        await self._backend.close()


class ProfileMediaStore(Protocol):
    """Port every profile-media backend satisfies: ``save``, ``read``, ``delete``.

    The profile facades (``iam`` for the patient photo, ``partner`` for the
    doctor photo) and routes never need to know the backing provider. The data
    methods are async and the local filesystem and Supabase backends implement
    them alike.

    ``save`` takes an opaque ``subject_id`` (the patient user id or the doctor
    partner id) plus the role ``prefix`` namespace it files under, so one port
    serves both the ``patient/`` and ``doctor/`` object spaces (ADR-0020 D1).

    ``close`` releases any resources the store owns (the Supabase backend's
    ``httpx.AsyncClient`` pool; a no-op locally). An app-lifetime store never
    calls it.
    """

    async def save(
        self,
        *,
        data: bytes,
        subject_id: int,
        prefix: str = PATIENT_PREFIX,
        object_key: str | None = None,
    ) -> str: ...

    async def read(self, *, object_key: str) -> bytes: ...

    async def delete(self, *, object_key: str) -> None: ...

    async def close(self) -> None: ...


def _encrypt(key: bytes, data: bytes) -> bytes:
    """AES-256-GCM-encrypt ``data`` with a fresh 12-byte nonce prepended."""
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _decrypt(key: bytes, payload: bytes) -> bytes:
    """Strip the prepended 12-byte nonce and AES-GCM-decrypt ``payload``."""
    nonce, ciphertext = payload[:12], payload[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _validate_object_key(object_key: str) -> Path:
    """Refuse an object key outside the ``patient/`` / ``doctor/`` prefixes (3 path parts)."""
    rel_path = Path(object_key)
    if len(rel_path.parts) != 3 or rel_path.parts[0] not in _SUPPORTED_PREFIXES:
        joined = ", ".join(sorted(_SUPPORTED_PREFIXES))
        raise OSError(f"object key is outside the supported prefixes ({joined})")
    return rel_path


def _validate_prefix(prefix: str) -> None:
    """Refuse a ``save`` under a prefix outside the pinned role layout.

    The object key layout is fixed by ADR-0020 D1 (``patient/<user-id>/...``,
    ``doctor/<user-id>/...``), so a write is refused before it files anything
    under a prefix that would then refuse to read back - including a
    ``../``-style prefix that could walk outside the local ``root``.
    """
    if prefix not in _SUPPORTED_PREFIXES:
        joined = ", ".join(sorted(_SUPPORTED_PREFIXES))
        raise OSError(f"prefix is outside the supported prefixes ({joined})")


def _build_profile_media_object_key(prefix: str, subject_id: int) -> str:
    _validate_prefix(prefix)
    return f"{prefix}/{subject_id}/{secrets.token_hex(16)}{_EXT}"


def _validate_save_object_key(
    object_key: str,
    *,
    prefix: str,
    subject_id: int,
) -> None:
    path = _validate_object_key(object_key)
    if path.parts[0] != prefix or path.parts[1] != str(subject_id):
        raise OSError("object key does not match the requested profile")


def _resolve_save_object_key(
    object_key: str | None,
    *,
    prefix: str,
    subject_id: int,
) -> str:
    if object_key is None:
        return _build_profile_media_object_key(prefix, subject_id)
    _validate_save_object_key(object_key, prefix=prefix, subject_id=subject_id)
    return object_key


class LocalFilesystemProfileMediaStore:
    """Encrypts and files profile-media bytes under ``patient/`` / ``doctor/`` on disk.

    The default dev/CI/test backend (``PROFILE_MEDIA_BACKEND=local``): ``root``
    is the private filesystem root (``var/``-style); objects land at
    ``<root>/<prefix>/<subject_id>/<uuid>.enc``. The object reference returned is
    that relative path under the role prefix, which the caller persists on the
    ``iam``/``partner`` profile row - never the photo bytes themselves. Never
    depends on the network, so local behavior is byte-identical across runs.
    """

    def __init__(self, root: Path | str, key_bytes: bytes | None = None) -> None:
        self._root = Path(root)
        if key_bytes is None:
            # Local-dev / test fallback: an ephemeral per-process key so the
            # encrypted write path always runs. Production must configure a
            # real key (security-phii-standards §4) - never commit one.
            key_bytes = secrets.token_bytes(32)
        if len(key_bytes) != 32:
            raise ValueError("ProfileMediaStore requires a 32-byte AES-256 key")
        self._key = key_bytes

    async def save(
        self,
        *,
        data: bytes,
        subject_id: int,
        prefix: str = PATIENT_PREFIX,
        object_key: str | None = None,
    ) -> str:
        """Encrypt ``data`` and file it, answering the ``<prefix>``-prefixed key.

        The key is the object-storage ref under the role ``prefix`` namespace
        (e.g. ``patient/42/<uuid>.enc`` or ``doctor/12/<uuid>.enc``); the caller
        stores it on the owning profile and streams reads through the store,
        never a public URL.

        Raises :class:`OSError` on a failed filesystem write - the caller wraps
        this in its upload-retry ladder so a flaky transfer never loses the
        photo silently.
        """
        object_key = _resolve_save_object_key(
            object_key,
            prefix=prefix,
            subject_id=subject_id,
        )
        path = self._root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_encrypt(self._key, data))
        return object_key

    async def read(self, *, object_key: str) -> bytes:
        """Decrypt and return the photo filed under ``object_key``.

        The mirror of :meth:`save`: reads ``<root>/<object_key>``, strips the
        prepended 12-byte nonce, and AES-GCM-decrypts with the same key,
        answering the original plaintext bytes. Called only after the caller's
        authorization check (owning patient or consent-gated doctor read) -
        bytes are never logged. Raises :class:`OSError` (or
        :class:`cryptography.exceptions.InvalidTag`) when the file is missing
        or the ciphertext is not authentic.
        """
        path = self._root / _validate_object_key(object_key)
        return _decrypt(self._key, path.read_bytes())

    async def delete(self, *, object_key: str) -> None:
        """Remove the photo filed under ``object_key``.

        The removal half of the upload contract (ADR-0020 D3): the caller clears
        the stored key on the profile and this deletes the ciphertext so a
        removed photo is not orphaned. Raises :class:`FileNotFoundError` when
        the object is already gone, matching the Supabase backend's 404.
        """
        path = self._root / _validate_object_key(object_key)
        path.unlink()

    async def close(self) -> None:
        """No resources to release: the local backend owns no network client."""


class SupabaseStorageProfileMediaStore:
    """Encrypts profile-media bytes into the private ``profile-media`` Supabase bucket.

    The durable production backend (ADR-0020): a Render free web service's disk
    is ephemeral (wiped on redeploy), so a photo saved only to local disk
    vanishes. This store talks to the Supabase Storage REST API over
    ``httpx.AsyncClient`` with the service-role key (never the client, ADR-0020
    D2), holding the SAME ciphertext (nonce + AES-256-GCM output) the local
    backend files - the provider never sees plaintext, so at-rest encryption
    stays owned by the app. Objects land under the same opaque
    ``patient/<user_id>/<uuid>.enc`` / ``doctor/<partner_id>/<uuid>.enc`` keys,
    so the profile key contract is backend-independent.

    ``client`` is injectable (``httpx.MockTransport`` in tests) so the remote
    path is exercised against a fake network, never real HTTP - the same
    constructor-injected-client pattern as the intake-media store.

    Error taxonomy mirrors the local backend exactly: any non-2xx on
    ``save``/``read``/``delete`` raises :class:`OSError` (a transient
    ``httpx.HTTPError`` transport failure is wrapped into it too, so the
    caller's upload-retry ladder sees the same failure class as a local disk
    error); a missing object on ``read``/``delete`` raises
    :class:`FileNotFoundError` (an ``OSError`` subclass); and a ciphertext whose
    GCM tag does not verify surfaces unchanged as
    :class:`cryptography.exceptions.InvalidTag`.
    """

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        bucket: str = MEDIA_BUCKET,
        key_bytes: bytes | None = None,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key
        self._bucket = bucket
        if key_bytes is None:
            # Same encoded-write-path fallback as the local backend: dev/test
            # derive an ephemeral per-process key; production boots one from
            # ``PROFILE_MEDIA_KEY`` (never committed).
            key_bytes = secrets.token_bytes(32)
        if len(key_bytes) != 32:
            raise ValueError("SupabaseStorageProfileMediaStore requires a 32-byte AES-256 key")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self._key = key_bytes
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._service_role_key}"}

    def _object_url(self, object_key: str) -> str:
        return f"{self._base_url}/{_STORAGE_OBJECT_ENDPOINT}/{self._bucket}/{object_key}"

    async def save(
        self,
        *,
        data: bytes,
        subject_id: int,
        prefix: str = PATIENT_PREFIX,
        object_key: str | None = None,
    ) -> str:
        """Encrypt ``data`` and POST the ciphertext, answering the opaque key.

        The same ``<prefix>/<subject_id>/<uuid>.enc`` key form as the local
        backend. The request body carries ONLY the nonce + GCM ciphertext - no
        plaintext media ever leaves the app. Raises :class:`OSError` when the
        upload is not acknowledged 2xx (the caller's retry ladder then wraps it
        as an upload failure).
        """
        object_key = _resolve_save_object_key(
            object_key,
            prefix=prefix,
            subject_id=subject_id,
        )
        try:
            response = await self._client.post(
                self._object_url(object_key),
                content=_encrypt(self._key, data),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProfileMediaStoreError(
                "profile media provider upload failed",
                retryable=True,
            ) from exc
        if not response.is_success:
            status_code = response.status_code
            raise ProfileMediaStoreError(
                "profile media provider rejected upload",
                retryable=_retryable_http_status(status_code),
                status_code=status_code,
            )
        return object_key

    async def read(self, *, object_key: str) -> bytes:
        """Download the ciphertext under ``object_key`` and decrypt it.

        The mirror of :meth:`save` against the same bucket. Raises
        :class:`FileNotFoundError` on a 404 (missing object), :class:`OSError`
        on any other non-2xx or transport failure, and
        :class:`cryptography.exceptions.InvalidTag` when the downloaded
        ciphertext is not authentic.
        """
        _validate_object_key(object_key)
        try:
            response = await self._client.get(
                self._object_url(object_key),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProfileMediaStoreError(
                "profile media provider read failed",
                retryable=True,
            ) from exc
        if response.status_code == 404:
            raise FileNotFoundError("profile media object was not found")
        if not response.is_success:
            status_code = response.status_code
            raise ProfileMediaStoreError(
                "profile media provider rejected read",
                retryable=_retryable_http_status(status_code),
                status_code=status_code,
            )
        return _decrypt(self._key, response.content)

    async def delete(self, *, object_key: str) -> None:
        """Remove the ciphertext under ``object_key`` from the bucket.

        The removal half of the upload contract (ADR-0020 D3), same bucket and
        service-role headers as save/read. Raises :class:`FileNotFoundError` on
        a 404 (object already gone) and :class:`OSError` on any other non-2xx or
        transport failure.
        """
        _validate_object_key(object_key)
        try:
            response = await self._client.request(
                "DELETE",
                self._object_url(object_key),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProfileMediaStoreError(
                "profile media provider delete failed",
                retryable=True,
            ) from exc
        if response.status_code == 404:
            raise FileNotFoundError("profile media object was not found")
        if not response.is_success:
            status_code = response.status_code
            raise ProfileMediaStoreError(
                "profile media provider rejected delete",
                retryable=_retryable_http_status(status_code),
                status_code=status_code,
            )
        return None

    async def close(self) -> None:
        """Release the owned ``httpx.AsyncClient`` connection pool.

        A store built without an injected client owns its pool (production). An
        injected client (tests) is left to its owner.
        """
        if self._owns_client:
            await self._client.aclose()


def decode_key(b64_key: str) -> bytes:
    """Decode a base64 AES-256 key, raising a clear error on malformed input."""
    try:
        return base64.b64decode(b64_key, validate=True)
    except ValueError as exc:
        raise ValueError("PROFILE_MEDIA_KEY is not valid base64") from exc


def build_profile_media_store(
    root: Path | str,
    b64_key: str,
    *,
    backend: str = "local",
    supabase_url: str = "",
    supabase_service_role_key: str = "",
    retry_policy: ProfileMediaRetryPolicy | None = None,
    timeout_seconds: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> ProfileMediaStore:
    """Build the store from config: local filesystem or private Supabase bucket.

    ``PROFILE_MEDIA_BACKEND`` selects the concrete store (ticket #532): ``local``
    (default, so dev/CI/tests are unchanged) files ciphertext under ``root``;
    ``supabase`` POSTs the same ciphertext into the private ``profile-media``
    bucket via ``supabase_url`` with ``supabase_service_role_key``. The remote
    path is fail-fast: both the URL and the service-role key are required, so a
    misconfigured production box never boots half-wired (the Settings layer
    enforces the same rule at boot). ``client`` is injectable only for tests
    (``httpx.MockTransport``); production lets the store own its client.

    ``root`` may be relative to the CWD (e.g. ``var/profile-media``), which
    ``create_app`` resolves to an absolute path. The no-key path derives an
    ephemeral dev/test key that still exercises the encrypted write path.
    """
    key_bytes = decode_key(b64_key) if b64_key else None
    if backend.strip().lower() == "supabase":
        if not supabase_url.strip() or not supabase_service_role_key.strip():
            raise ValueError(
                "profile_media_backend='supabase' requires both SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY"
            )
        if retry_policy is None:
            raise ValueError("Supabase profile media requires a retry policy")
        if timeout_seconds is None:
            raise ValueError("Supabase profile media requires a timeout")
        remote_store = SupabaseStorageProfileMediaStore(
            supabase_url=supabase_url,
            service_role_key=supabase_service_role_key,
            key_bytes=key_bytes,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        return ResilientProfileMediaStore(remote_store, retry_policy)
    return LocalFilesystemProfileMediaStore(root=root, key_bytes=key_bytes)
