"""MOD-014: AES-256-GCM encryption for dashboard-entered provider API keys in
ops settings (issue #921).

Pins the encrypt/decrypt round-trip and error paths for the setting encryption
against the ``cryptography`` AESGCM primitive without a database.
"""

from __future__ import annotations

import base64
import os

import pytest

from modules.ops.domain.setting_encryption import (
    SettingEncryptionError,
    decrypt_setting_value,
    encrypt_setting_value,
    is_encrypted_value,
)
from modules.ops.domain.setting_encryption_service import SettingEncryptionService

_ENCRYPTION_KEY = base64.b64encode(os.urandom(32)).decode("ascii")
_OTHER_KEY = base64.b64encode(os.urandom(32)).decode("ascii")


def test_encrypt_decrypt_round_trip() -> None:
    plaintext = "sk-test-api-key-12345"

    encrypted = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)
    decrypted = decrypt_setting_value(encrypted, _ENCRYPTION_KEY)

    assert decrypted == plaintext


def test_same_plaintext_yields_different_ciphertext() -> None:
    plaintext = "sk-test-api-key-12345"

    enc1 = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)
    enc2 = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)

    assert enc1 != enc2  # random nonce


def test_decrypt_with_wrong_key_fails() -> None:
    from cryptography.exceptions import InvalidTag

    encrypted = encrypt_setting_value("sk-test-api-key-12345", _ENCRYPTION_KEY)

    with pytest.raises(InvalidTag):
        decrypt_setting_value(encrypted, _OTHER_KEY)


def test_decrypt_tampered_ciphertext_fails() -> None:
    from cryptography.exceptions import InvalidTag

    encrypted = encrypt_setting_value("sk-test-api-key-12345", _ENCRYPTION_KEY)
    raw = base64.b64decode(encrypted)
    # Flip a byte in the ciphertext portion (after the 12-byte nonce).
    tampered = bytearray(raw)
    tampered[20] ^= 0xFF
    tampered_encrypted = base64.b64encode(bytes(tampered)).decode("ascii")

    with pytest.raises(InvalidTag):
        decrypt_setting_value(tampered_encrypted, _ENCRYPTION_KEY)


def test_decrypt_short_blob_fails() -> None:
    short = base64.b64encode(b"too-short").decode("ascii")

    with pytest.raises(SettingEncryptionError, match="too short"):
        decrypt_setting_value(short, _ENCRYPTION_KEY)


def test_decode_key_rejects_non_base64() -> None:
    with pytest.raises(SettingEncryptionError, match="valid base64"):
        encrypt_setting_value("test", "!!!not-base64!!!")


def test_decode_key_rejects_wrong_length() -> None:
    short_key = base64.b64encode(b"short").decode("ascii")
    with pytest.raises(SettingEncryptionError, match="32 bytes"):
        encrypt_setting_value("test", short_key)


def test_is_encrypted_value_detects_encrypted() -> None:
    plaintext = "sk-test-api-key-12345"
    encrypted = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)

    assert is_encrypted_value(encrypted) is True
    assert is_encrypted_value(plaintext) is False
    assert is_encrypted_value("not-base64!@#") is False
    assert is_encrypted_value("") is False


def test_encrypt_empty_string_raises() -> None:
    with pytest.raises(SettingEncryptionError, match="empty string"):
        encrypt_setting_value("", _ENCRYPTION_KEY)


def test_encrypt_json_value() -> None:
    import json

    plaintext = json.dumps({"key": "value", "nested": {"a": 1}}, separators=(",", ":"))
    encrypted = encrypt_setting_value(plaintext, _ENCRYPTION_KEY)
    decrypted = decrypt_setting_value(encrypted, _ENCRYPTION_KEY)

    assert json.loads(decrypted) == json.loads(plaintext)


# --- SettingEncryptionService unit tests ---


def test_service_encrypt_if_needed_skips_non_encrypted_key() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    assert service.encrypt_if_needed("ai.timeout_seconds", 15) == 15


def test_service_encrypt_if_needed_skips_empty_value() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    assert service.encrypt_if_needed("ai.api_key", "") == ""
    assert service.encrypt_if_needed("ai.api_key", None) is None


def test_service_encrypt_if_needed_encrypts_encrypted_key() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    encrypted = service.encrypt_if_needed("ai.api_key", "test-plaintext-value")
    from modules.ops.domain.setting_encryption import is_encrypted_value

    assert is_encrypted_value(encrypted) is True
    assert encrypted != "test-plaintext-value"


def test_service_redact_value_redacts_encrypted_value() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    encrypted = service.encrypt_if_needed("ai.api_key", "test-plaintext-value")
    redacted = service.redact_value("ai.api_key", encrypted)
    assert redacted != "test-plaintext-value"
    assert redacted.startswith("[") and redacted.endswith("]")


def test_service_redact_value_does_not_redact_plaintext() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    assert service.redact_value("ai.api_key", "test-plaintext-value") == "test-plaintext-value"


def test_service_redact_value_skips_non_encrypted_key() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    assert service.redact_value("ai.timeout_seconds", 15) == 15


def test_service_masked_status_configured_from_environment() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    status = service.get_masked_status("ai.api_key", "environment")
    assert status == "missing"  # no DB value, no history -> missing


def test_service_masked_status_configured_from_dashboard_with_timestamp() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    status = service.get_masked_status(
        "ai.api_key",
        "database",
        db_value="v1:...",
        history_reader=lambda k: "2024-01-15T10:30:00+00:00",
    )
    assert status == "configured from dashboard, set 2024-01-15T10:30:00+00:00"


def test_service_masked_status_configured_from_dashboard_no_timestamp() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    status = service.get_masked_status(
        "ai.api_key",
        "database",
        db_value="v1:...",
        history_reader=None,
    )
    assert status == "configured from dashboard"


def test_service_masked_status_non_encrypted_key_returns_empty() -> None:
    service = SettingEncryptionService(_ENCRYPTION_KEY)
    assert service.get_masked_status("ai.timeout_seconds", "database", db_value=15) == ""


def test_service_disabled_when_no_encryption_key() -> None:
    service = SettingEncryptionService("")
    assert service._enabled is False
    # No-op when disabled
    assert service.encrypt_if_needed("ai.api_key", "test-plaintext-value") == "test-plaintext-value"
    assert service.redact_value("ai.api_key", "v1:abc") == "v1:abc"
    assert service.get_masked_status("ai.api_key", "database", db_value="v1:abc") == ""
