"""MOD-005 (PHASE-7 T08, ticket #352; fix #385): encrypted intake-media store.

Audio voice notes are PHI (security-phii-standards: audio is PHI, encryption at
rest, ``intake/`` object prefix), so the raw bytes are never written or
transmitted in the clear. This adapter encrypts each clip with AES-256-GCM (the
``cryptography`` package - the only crypto dependency the cost floor ``NFR-001``
admits, same choice as the partner artifact store) and answers an opaque
``intake/``-prefixed object key. Only that ref (plus duration/size metadata) is
persisted in ``intake_media_refs`` - never the audio bytes and never the
plaintext.

Two concrete backends sit behind the ``IntakeMediaStore`` port, selected by
``INTAKE_MEDIA_BACKEND`` and resolved by the :func:`build_media_store` factory:

- **local** (default): files the ciphertext under the repository ``var/`` root
  under ``intake/<patient_id>/``. Used by dev/CI/tests so nothing depends on
  the network; byte-identical to the pre-#385 behavior.
- **supabase** (production): POSTs the ciphertext into a private Supabase
  Storage bucket via the ``/storage/v1/object/{bucket}/{object_key}`` REST API
  over ``httpx.AsyncClient`` with the service-role key. The provider only ever
  sees ciphertext - at-rest encryption stays owned by the app
  (security-phii-standards), and an ephemeral Render disk can never wipe a
  capture on redeploy.

The caller never touches bytes: ``upload_intake_media`` hands a raw clip to the
store and gets back the ref. This adapter is a thin seam (coding-standards
A-S3, adapter has no policy) - the upload-resilience retry/backoff ladder and
the typed ``MediaTransferError`` live in the facade, mirroring how EXT-002
retry discipline is enforced at the seam, not in the concrete store.

The key is a base64 32-byte value from the environment (``INTAKE_MEDIA_KEY``),
required in production and never committed. For local-dev/test where no key is
configured, the store derives an ephemeral per-process key so the encrypted
write path is exercised (same convention as the partner artifact store).
"""

from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import Final, Protocol

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Object-storage prefix under which every intake media clip is filed.
PREFIX: Final[str] = "intake"

#: Private Supabase Storage bucket holding the ciphertext (ticket #385). The
#: bucket is created private at provisioning - audio is only reachable through
#: the authenticated intake API routes, never served from a public bucket.
MEDIA_BUCKET: Final[str] = "intake-media"

_EXT = ".enc"

_STORAGE_OBJECT_ENDPOINT = "storage/v1/object"

#: Explicit outbound-call ceiling for the Storage REST API (third-party-
#: integration-standards: timeout always set explicitly, no unbounded waits).
#: Mirrors the EXT-002 gateway's 30s cap - a hung upload must fail into the
#: facade retry ladder, never block the request forever.
_STORAGE_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(30.0)


class IntakeMediaStore(Protocol):
    """Port every intake-media backend satisfies: ``save`` then ``read``.

    Exactly two operations (ticket #385 US-5) - the facade, routes, and
    pipeline never need to know the backing provider. Both methods are async:
    the local filesystem backend and the Supabase backend implement them alike.
    """

    async def save(self, *, data: bytes, patient_id: int) -> str: ...

    async def read(self, *, object_key: str) -> bytes: ...


def _encrypt(key: bytes, data: bytes) -> bytes:
    """AES-256-GCM-encrypt ``data`` with a fresh 12-byte nonce prepended."""
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _decrypt(key: bytes, payload: bytes) -> bytes:
    """Strip the prepended 12-byte nonce and AES-GCM-decrypt ``payload``."""
    nonce, ciphertext = payload[:12], payload[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _validate_object_key(object_key: str) -> Path:
    """Refuse an object key outside the ``intake/`` prefix (3 path parts)."""
    rel_path = Path(object_key)
    if rel_path.parts[0] != PREFIX or len(rel_path.parts) != 3:
        raise OSError(f"object key is outside the {PREFIX}/ prefix")
    return rel_path


class LocalFilesystemIntakeMediaStore:
    """Encrypts and files intake-audio bytes under ``intake/`` on the local disk.

    The default dev/CI/test backend (``INTAKE_MEDIA_BACKEND=local``): ``root``
    is the private filesystem root (``var/``-style); clips land at
    ``<root>/intake/<patient_id>/<uuid>.enc``. The object reference returned is
    that relative path under the ``intake/`` prefix, which the facade persists
    in ``intake_media_refs.object_key`` - never the audio bytes themselves.
    Never depends on the network, so local behavior is byte-identical to the
    pre-#385 store.
    """

    def __init__(self, root: Path | str, key_bytes: bytes | None = None) -> None:
        self._root = Path(root)
        if key_bytes is None:
            # Local-dev / test fallback: an ephemeral per-process key so the
            # encrypted write path always runs. Production must configure a
            # real key (security-phii-standards §4) - never commit one.
            key_bytes = secrets.token_bytes(32)
        if len(key_bytes) != 32:
            raise ValueError("IntakeMediaStore requires a 32-byte AES-256 key")
        self._key = key_bytes

    async def save(self, *, data: bytes, patient_id: int) -> str:
        """Encrypt ``data`` and file it, answering the ``intake/``-prefixed ref.

        The ref is the clip's object-storage key under the ``intake/`` prefix
        (e.g. ``intake/42/<uuid>.enc``); the facade stores it in
        ``intake_media_refs.object_key`` and surfaces it to the doctor on
        review, never the audio plaintext.

        Raises :class:`OSError` on a failed filesystem write - the facade wraps
        this in its upload-resilience retry ladder so a flaky transfer never
        loses the capture silently.
        """
        return self._write(patient_id, _encrypt(self._key, data))

    def _write(self, patient_id: int, payload: bytes) -> str:
        directory = self._root / PREFIX / str(patient_id)
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{secrets.token_hex(16)}{_EXT}"
        path = directory / filename
        path.write_bytes(payload)
        return f"{PREFIX}/{patient_id}/{filename}"

    async def read(self, *, object_key: str) -> bytes:
        """Decrypt and return the clip filed under ``object_key``.

        The mirror of :meth:`save`: reads ``<root>/<object_key>``, strips the
        prepended 12-byte nonce, and AES-GCM-decrypts with the same key,
        answering the original plaintext audio bytes. Called only after a
        facade-level authorization check (owning patient or reviewing doctor) -
        bytes are never logged. Raises :class:`OSError` (or
        :class:`cryptography.exceptions.InvalidTag`) when the file is missing
        or the ciphertext is not authentic.
        """
        path = self._root / _validate_object_key(object_key)
        return _decrypt(self._key, path.read_bytes())


class SupabaseStorageIntakeMediaStore:
    """Encrypts intake-audio bytes into a private Supabase Storage bucket.

    The durable production backend (ticket #385): a Render free web service's
    disk is ephemeral (wiped on redeploy), so a capture saved only to local
    disk vanishes. This store talks to the Supabase Storage REST API over
    ``httpx.AsyncClient`` with the service-role key, holding the SAME
    ciphertext (nonce + AES-256-GCM output) the local backend files - the
    provider never sees plaintext, so at-rest encryption stays owned by the
    app. Objects land under the same opaque ``intake/<patient_id>/<uuid>.enc``
    keys, so the ``intake_media_refs.object_key`` contract and every consumer
    are unchanged.

    ``client`` is injectable (``httpx.MockTransport`` in tests) so the remote
    path is exercised against a fake network, never real HTTP - the same
    constructor-injected-client pattern as
    ``build_openai_compatible_gateway`` (prior art: ``test_ai_gateway_*``).

    Error taxonomy mirrors the local backend exactly: any non-2xx on
    ``save``/``read`` raises :class:`OSError` (a transient ``httpx.HTTPError``
    transport failure is wrapped into it too, so the facade's upload retry
    ladder sees the same failure class as a local disk error); a missing object
    on ``read`` raises :class:`FileNotFoundError` (an ``OSError`` subclass);
    and a ciphertext whose GCM tag does not verify surfaces unchanged as
    :class:`cryptography.exceptions.InvalidTag`.
    """

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        bucket: str = MEDIA_BUCKET,
        key_bytes: bytes | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key
        self._bucket = bucket
        if key_bytes is None:
            # Same encoded-write-path fallback as the local backend: dev/test
            # derive an ephemeral per-process key; production boots one from
            # ``INTAKE_MEDIA_KEY`` (never committed).
            key_bytes = secrets.token_bytes(32)
        if len(key_bytes) != 32:
            raise ValueError("SupabaseStorageIntakeMediaStore requires a 32-byte AES-256 key")
        self._key = key_bytes
        self._client = client or httpx.AsyncClient(timeout=_STORAGE_TIMEOUT)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._service_role_key}"}

    def _object_url(self, object_key: str) -> str:
        return f"{self._base_url}/{_STORAGE_OBJECT_ENDPOINT}/{self._bucket}/{object_key}"

    async def save(self, *, data: bytes, patient_id: int) -> str:
        """Encrypt ``data`` and POST the ciphertext, answering the opaque ref.

        The same ``intake/<patient_id>/<uuid>.enc`` key form as the local
        backend. The request body carries ONLY the nonce + GCM ciphertext - no
        plaintext audio ever leaves the app. Raises :class:`OSError` when the
        upload is not acknowledged 2xx (the facade's retry ladder then wraps it
        into ``MediaTransferError`` unchanged, at most 3 attempts).
        """
        object_key = f"{PREFIX}/{patient_id}/{secrets.token_hex(16)}{_EXT}"
        try:
            response = await self._client.post(
                self._object_url(object_key),
                content=_encrypt(self._key, data),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise OSError(
                f"failed to reach Supabase Storage uploading object {object_key}"
            ) from exc
        if not response.is_success:
            raise OSError(
                f"Supabase Storage refused object {object_key} with HTTP {response.status_code}"
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
            raise OSError(f"failed to reach Supabase Storage reading object {object_key}") from exc
        if response.status_code == 404:
            raise FileNotFoundError(f"object {object_key} not found in Supabase Storage")
        if not response.is_success:
            raise OSError(
                f"Supabase Storage refused object {object_key} with HTTP {response.status_code}"
            )
        return _decrypt(self._key, response.content)


def decode_key(b64_key: str) -> bytes:
    """Decode a base64 AES-256 key, raising a clear error on malformed input."""
    try:
        return base64.b64decode(b64_key, validate=True)
    except ValueError as exc:
        raise ValueError("INTAKE_MEDIA_KEY is not valid base64") from exc


def build_media_store(
    root: Path | str,
    b64_key: str,
    *,
    backend: str = "local",
    supabase_url: str = "",
    supabase_service_role_key: str = "",
    client: httpx.AsyncClient | None = None,
) -> IntakeMediaStore:
    """Build the store from config: local filesystem or private Supabase bucket.

    ``INTAKE_MEDIA_BACKEND`` selects the concrete store (ticket #385): ``local``
    (default, so dev/CI/tests are unchanged) files ciphertext under ``root``;
    ``supabase`` POSTs the same ciphertext into a private bucket via
    ``supabase_url`` with ``supabase_service_role_key``. The remote path is
    fail-fast: both the URL and the service-role key are required, so a
    misconfigured production box never boots half-wired (the Settings layer
    enforces the same rule at boot). ``client`` is injectable only for tests
    (``httpx.MockTransport``); production lets the store own its client.

    ``root`` may be relative to the CWD (e.g. ``var/intake-media``), which
    ``create_app`` resolves to an absolute path. The no-key path derives an
    ephemeral dev/test key that still exercises the encrypted write path.
    """
    key_bytes = decode_key(b64_key) if b64_key else None
    if backend.strip().lower() == "supabase":
        if not supabase_url.strip() or not supabase_service_role_key.strip():
            raise ValueError(
                "intake_media_backend='supabase' requires both SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY"
            )
        return SupabaseStorageIntakeMediaStore(
            supabase_url=supabase_url,
            service_role_key=supabase_service_role_key,
            key_bytes=key_bytes,
            client=client,
        )
    return LocalFilesystemIntakeMediaStore(root=root, key_bytes=key_bytes)
