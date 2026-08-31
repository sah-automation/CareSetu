"""MOD-002: encrypted credential-document store (PHASE-5 T06, ticket #251).

The ``partner/`` object-storage prefix for credential documents (ADR-0008,
security-phii-standards §1/§5): a sensitive-class store - not PHI, but access and
retention are restricted. Artifact bytes are encrypted at rest with AES-256-GCM
(the ``cryptography`` package - the only crypto dependency the cost floor
``NFR-001`` admits) and written to a private local directory under the repository
``var/`` root; only object references ("refs") are stored in
``partner_credentials.artifact_refs`` - never the document bytes themselves, and
never the plaintext.

Access control is the facade's job: the owner submits (writes) on their own
behalf, the reviewing operator reads during Step-2 (T08) and every view is
audited (``partner.credential_reviewed``). This adapter only encrypts/writes and
returns the opaque ref; it holds no per-caller policy so the caller cannot
scramble the boundary (coding-standards §3, adapter is a thin seam).

The AES key is a base64 32-byte value from the environment
(``PARTNER_ARTIFACT_KEY``), required in production and never committed. For
local-dev/test where no key is configured, the store derives an ephemeral key
per process so the encrypted write path is exercised without a secret in code.
"""

from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Object-storage prefix under which every partner artifact is filed.
PREFIX: Final[str] = "partner"

#: Filename separator between the credential type and the per-credential index.
_INDEX_SEP = "_"
_EXT = ".enc"


class CredentialArtifactStore:
    """Encrypts and files credential-document bytes under ``partner/``.

    ``root`` is the private filesystem root (``var/``-style); artifacts land at
    ``<root>/partner/<partner_id>/<credential_type>_<index>.enc``. The object
    reference returned is that relative path under the ``partner/`` prefix, which
    is what gets persisted in ``partner_credentials.artifact_refs``.
    """

    def __init__(self, root: Path | str, key_bytes: bytes | None = None) -> None:
        self._root = Path(root)
        if key_bytes is None:
            # Local-dev / test fallback: an ephemeral per-process key so the
            # encrypted write path always runs. Production must configure a real
            # key (security-phii-standards §4) - never commit one.
            key_bytes = secrets.token_bytes(32)
        if len(key_bytes) != 32:
            raise ValueError("CredentialArtifactStore requires a 32-byte AES-256 key")
        self._key = key_bytes

    def save_artifact(self, partner_id: int, credential_type: str, index: int, data: bytes) -> str:
        """Encrypt ``data`` and file it, answering the ``partner/``-prefixed ref.

        The ref is the artifact's object-storage key under the ``partner/``
        prefix (e.g. ``partner/42/medical_registration_0.enc``); the facade
        stores it in ``partner_credentials.artifact_refs`` and surfaces it to
        the operator queue on review, never the plaintext.
        """
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, data, None)
        return self._write(partner_id, credential_type, index, nonce + ciphertext)

    def _write(self, partner_id: int, credential_type: str, index: int, payload: bytes) -> str:
        directory = self._root / PREFIX / str(partner_id)
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{credential_type}{_INDEX_SEP}{index}{_EXT}"
        path = directory / filename
        path.write_bytes(payload)
        return f"{PREFIX}/{partner_id}/{filename}"


def decode_key(b64_key: str) -> bytes:
    """Decode a base64 AES-256 key, raising a clear error on malformed input."""
    try:
        return base64.b64decode(b64_key, validate=True)
    except ValueError as exc:
        raise ValueError("PARTNER_ARTIFACT_KEY is not valid base64") from exc


def build_artifact_store(root: Path | str, b64_key: str) -> CredentialArtifactStore:
    """Build the store from config: decode the env key, else derive ephemeral.

    The explicit-key path is how production boots (a real key from the
    environment); the no-key path is the dev/test store that still exercises the
    same encrypted write path. ``root`` may be relative to the CWD (e.g.
    ``var/partner-artifacts``), which ``create_app`` resolves to an absolute path.
    """
    key_bytes = decode_key(b64_key) if b64_key else None
    return CredentialArtifactStore(root=root, key_bytes=key_bytes)
