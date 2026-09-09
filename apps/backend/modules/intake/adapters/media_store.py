"""MOD-005 (PHASE-7 T08, ticket #352): encrypted intake-media object store.

Audio voice notes are PHI (security-phii-standards : air SM1/2: audio is PHI,
encryption at rest, ``intake/`` object prefix), so the raw bytes are never
written to disk in the clear. This adapter encrypts each clip with AES-256-GCM
(the ``cryptography`` package - the only crypto dependency the cost floor
``NFR-001`` admits, same choice as the partner artifact store) and files it
under the repository ``var/`` root under the ``intake/<patient_id>/`` prefix,
answering an opaque ``intake/``-prefixed object key. Only that ref (plus
duration/size metadata) is persisted in ``intake_media_refs`` - never the audio
bytes and never the plaintext.

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
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Object-storage prefix under which every intake media clip is filed.
PREFIX: Final[str] = "intake"

_EXT = ".enc"


class IntakeMediaStore:
    """Encrypts and files intake-audio bytes under ``intake/``.

    ``root`` is the private filesystem root (``var/``-style); clips land at
    ``<root>/intake/<patient_id>/<uuid>.enc``. The object reference returned is
    that relative path under the ``intake/`` prefix, which the facade persists
    in ``intake_media_refs.object_key`` - never the audio bytes themselves.
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

    def save(self, *, data: bytes, patient_id: int) -> str:
        """Encrypt ``data`` and file it, answering the ``intake/``-prefixed ref.

        The ref is the clip's object-storage key under the ``intake/`` prefix
        (e.g. ``intake/42/<uuid>.enc``); the facade stores it in
        ``intake_media_refs.object_key`` and surfaces it to the doctor on
        review, never the audio plaintext.

        Raises :class:`OSError` on a failed filesystem write - the facade wraps
        this in its upload-resilience retry ladder so a flaky transfer never
        loses the capture silently.
        """
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, data, None)
        return self._write(patient_id, nonce + ciphertext)

    def _write(self, patient_id: int, payload: bytes) -> str:
        directory = self._root / PREFIX / str(patient_id)
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{secrets.token_hex(16)}{_EXT}"
        path = directory / filename
        path.write_bytes(payload)
        return f"{PREFIX}/{patient_id}/{filename}"

    def read(self, *, object_key: str) -> bytes:
        """Decrypt and return the clip filed under ``object_key``.

        The mirror of :meth:`save`: reads ``<root>/<object_key>``, strips the
        prepended 12-byte nonce, and AES-GCM-decrypts with the same key,
        answering the original plaintext audio bytes. Called only after a
        facade-level authorization check (owning patient or reviewing doctor) -
        bytes are never logged. Raises :class:`OSError` (or
        :class:`cryptography.exceptions.InvalidTag`) when the file is missing
        or the ciphertext is not authentic.
        """
        rel_path = Path(object_key)
        if rel_path.parts[0] != PREFIX or len(rel_path.parts) != 3:
            raise OSError(f"object key is outside the {PREFIX}/ prefix")
        path = self._root / rel_path
        payload = path.read_bytes()
        nonce, ciphertext = payload[:12], payload[12:]
        return AESGCM(self._key).decrypt(nonce, ciphertext, None)


def decode_key(b64_key: str) -> bytes:
    """Decode a base64 AES-256 key, raising a clear error on malformed input."""
    try:
        return base64.b64decode(b64_key, validate=True)
    except ValueError as exc:
        raise ValueError("INTAKE_MEDIA_KEY is not valid base64") from exc


def build_media_store(root: Path | str, b64_key: str) -> IntakeMediaStore:
    """Build the store from config: decode the env key, else derive ephemeral.

    The explicit-key path is how production boots (a real key from the
    environment); the no-key path is the dev/test store that still exercises
    the same encrypted write path. ``root`` may be relative to the CWD (e.g.
    ``var/intake-media``), which ``create_app`` resolves to an absolute path.
    """
    key_bytes = decode_key(b64_key) if b64_key else None
    return IntakeMediaStore(root=root, key_bytes=key_bytes)
