"""MOD-001: AES-256-GCM encryption for TOTP secrets (S8, #261).

Pins the encrypt/decrypt round-trip and error paths for the TOTP secret
storage against the ``cryptography`` AESGCM primitive without a database.
"""

from __future__ import annotations

import base64
import os

import pytest

from modules.iam.domain.secret_encryption import (
    decrypt_secret,
    encrypt_secret,
)

_MFA_KEY = base64.b64encode(os.urandom(32)).decode("ascii")
_OTHER_KEY = base64.b64encode(os.urandom(32)).decode("ascii")


def test_encrypt_decrypt_round_trip() -> None:
    plaintext = "JBSWY3DPEHPK3PXP"

    encrypted = encrypt_secret(plaintext, _MFA_KEY)
    decrypted = decrypt_secret(encrypted, _MFA_KEY)

    assert decrypted == plaintext


def test_same_plaintext_yields_different_ciphertext() -> None:
    plaintext = "JBSWY3DPEHPK3PXP"

    enc1 = encrypt_secret(plaintext, _MFA_KEY)
    enc2 = encrypt_secret(plaintext, _MFA_KEY)

    assert enc1 != enc2  # random nonce


def test_decrypt_with_wrong_key_fails() -> None:
    from cryptography.exceptions import InvalidTag

    encrypted = encrypt_secret("JBSWY3DPEHPK3PXP", _MFA_KEY)

    with pytest.raises(InvalidTag):
        decrypt_secret(encrypted, _OTHER_KEY)


def test_decrypt_tampered_ciphertext_fails() -> None:
    from cryptography.exceptions import InvalidTag

    encrypted = encrypt_secret("JBSWY3DPEHPK3PXP", _MFA_KEY)
    raw = base64.b64decode(encrypted)
    # Flip a byte in the ciphertext portion (after the 12-byte nonce).
    tampered = bytearray(raw)
    tampered[20] ^= 0xFF
    tampered_encrypted = base64.b64encode(bytes(tampered)).decode("ascii")

    with pytest.raises(InvalidTag):
        decrypt_secret(tampered_encrypted, _MFA_KEY)


def test_decrypt_short_blob_fails() -> None:
    short = base64.b64encode(b"too-short").decode("ascii")

    with pytest.raises(ValueError, match="too short"):
        decrypt_secret(short, _MFA_KEY)


def test_decode_key_rejects_non_base64() -> None:
    with pytest.raises(ValueError, match="valid base64"):
        encrypt_secret("test", "!!!not-base64!!!")


def test_decode_key_rejects_wrong_length() -> None:
    short_key = base64.b64encode(b"short").decode("ascii")
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_secret("test", short_key)
