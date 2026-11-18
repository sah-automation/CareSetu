"""MOD-014: AES-256-GCM encryption for dashboard-entered provider API keys in
ops settings (issue #921).

Follows the same AESGCM pattern the IAM TOTP secret encryption uses
(``modules.iam.domain.secret_encryption``) but for string values stored in
``ops.ops_settings.value`` (JSONB). The key is a base64-encoded 32-byte
AES-256 value from the environment (never committed, security-phii-standards
S4/S5); decryption is deferred to internal use only.

The ciphertext is ``nonce || ciphertext || tag`` base64-encoded, identical to
the ``AESGCM.encrypt`` / ``AESGCM.decrypt`` contract. The nonce is
randomly generated per encryption call so the same plaintext yields different
ciphertext (semantic security).
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: AES-256 requires a 32-byte key.
_REQUIRED_KEY_BYTES = 32


class SettingEncryptionError(ValueError):
    """Raised when setting encryption/decryption fails."""


def _decode_key(b64_key: str) -> bytes:
    """Decode a base64 AES-256 key, raising on malformed input."""
    try:
        key = base64.b64decode(b64_key)
    except Exception as exc:
        raise SettingEncryptionError(
            f"ops_settings_encryption_key must be a valid base64 string; got {type(exc).__name__}"
        ) from exc
    if len(key) != _REQUIRED_KEY_BYTES:
        raise SettingEncryptionError(
            f"ops_settings_encryption_key must be exactly {_REQUIRED_KEY_BYTES} bytes "
            f"({_REQUIRED_KEY_BYTES * 8}-bit AES); got {len(key)} bytes"
        )
    return key


def encrypt_setting_value(plaintext: str, b64_key: str) -> str:
    """Encrypt a plaintext setting value with AES-256-GCM.

    Returns a base64-encoded ``nonce || ciphertext || tag`` blob suitable for
    storage in the ``ops.ops_settings.value`` JSONB column.

    Raises:
        SettingEncryptionError: If plaintext is empty.
    """
    if not plaintext:
        raise SettingEncryptionError("cannot encrypt empty string")

    key = _decode_key(b64_key)
    nonce = os.urandom(12)  # 96-bit nonce per AES-GCM convention
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_setting_value(encrypted: str, b64_key: str) -> str:
    """Decrypt an AES-256-GCM-encrypted setting value.

    Returns the plaintext string. Raises on decryption failure
    (wrong key, tampered ciphertext, or truncated blob).
    """
    key = _decode_key(b64_key)
    raw = base64.b64decode(encrypted)
    # nonce is 12 bytes, tag is 16 bytes; minimum ciphertext is 1 byte.
    if len(raw) < 12 + 16 + 1:
        raise SettingEncryptionError("encrypted setting value is too short or corrupted")
    nonce = raw[:12]
    ciphertext_with_tag = raw[12:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext_with_tag, None)
    return plaintext.decode("utf-8")


def is_encrypted_value(value: str) -> bool:
    """Check if a string value appears to be an encrypted blob.

    Encrypted values are base64-encoded and at least 29 bytes (12 nonce + 16 tag + 1 ciphertext).
    """
    try:
        raw = base64.b64decode(value)
        return len(raw) >= 29
    except Exception:
        return False
