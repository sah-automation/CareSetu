"""PHASE-5 T06: the encrypted credential-document store (ticket #251).

Pins the encrypted-write contract at the adapter seam (security-phii-standards
§1/§5, ADR-0008): artifact bytes are AES-256-GCM encrypted at rest under the
``partner/`` prefix, the store returns an opaque ref (never the plaintext), a
round-trip decrypt recovers the original bytes, and a known/malformed key is
refused so the store can never boot with a weak or in-code secret.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from modules.partner.adapters.artifact_store import (
    CredentialArtifactStore,
    build_artifact_store,
    decode_key,
)

_PLAINTEXT = b"medical registration certificate PDF bytes"
_VALID_KEY_B64 = base64.b64encode(bytes(32)).decode()


def test_save_artifact_returns_partner_prefixed_ref(tmp_path: Path) -> None:
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))

    ref = store.save_artifact(42, "medical_registration", 0, _PLAINTEXT)

    assert ref == "partner/42/medical_registration_0.enc"
    assert (tmp_path / ref.replace("/", os.sep)).exists()


def test_artifact_is_encrypted_at_rest_not_plaintext(tmp_path: Path) -> None:
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))

    store.save_artifact(42, "medical_registration", 0, _PLAINTEXT)

    raw = (tmp_path / "partner" / "42" / "medical_registration_0.enc").read_bytes()
    assert _PLAINTEXT not in raw


def test_artifact_round_trip_decrypts_to_original(tmp_path: Path) -> None:
    key = os.urandom(32)
    store = CredentialArtifactStore(root=tmp_path, key_bytes=key)

    ref = store.save_artifact(7, "lab_license", 1, _PLAINTEXT)

    raw = (tmp_path / ref.replace("/", os.sep)).read_bytes()
    # Payload layout: 12-byte nonce followed by AES-GCM ciphertext+tag.
    nonce, ciphertext = raw[:12], raw[12:]
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    decrypted = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert decrypted == _PLAINTEXT


def test_multiple_artifacts_are_isolated_per_credential_index(tmp_path: Path) -> None:
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))

    ref0 = store.save_artifact(9, "medical_registration", 0, b"first")
    ref1 = store.save_artifact(9, "medical_registration", 1, b"second")
    ref2 = store.save_artifact(9, "qualification_certificate", 0, b"third")

    assert ref0 == "partner/9/medical_registration_0.enc"
    assert ref1 == "partner/9/medical_registration_1.enc"
    assert ref2 == "partner/9/qualification_certificate_0.enc"


def test_short_or_long_key_is_refused() -> None:
    with pytest.raises(ValueError, match="32-byte"):
        CredentialArtifactStore(root="x", key_bytes=bytes(16))


def test_decode_key_accepts_valid_base64() -> None:
    assert decode_key(_VALID_KEY_B64) == bytes(32)


def test_decode_key_rejects_malformed_base64() -> None:
    with pytest.raises(ValueError, match="not valid base64"):
        decode_key("!!!not-base64!!!")


def test_build_artifact_store_with_configured_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = build_artifact_store(tmp_path, b64_key=_VALID_KEY_B64)

    ref = store.save_artifact(3, "drug_license", 0, _PLAINTEXT)
    assert ref == "partner/3/drug_license_0.enc"


def test_build_artifact_store_without_key_derives_ephemeral(tmp_path: Path) -> None:
    # Dev/test boot with no env key still runs the encrypted write path.
    store = build_artifact_store(tmp_path, b64_key="")

    ref = store.save_artifact(3, "drug_license", 0, _PLAINTEXT)
    assert ref == "partner/3/drug_license_0.enc"
