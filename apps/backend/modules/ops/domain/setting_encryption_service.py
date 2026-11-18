# ruff: noqa: I001
"""MOD-014: Encryption service for ops settings (issue #921).

Provides a dedicated service for encrypting/decrypting/redacting setting values
that are marked as encrypted. This separates encryption concerns from the
facade's CRUD logic.
"""

from collections.abc import Callable
from typing import Any

from modules.ops.domain.setting_encryption import (
    encrypt_setting_value,
    is_encrypted_value,
    SettingEncryptionError,
)
from modules.ops.domain.settings import ENCRYPTED_SETTING_KEYS


#: Callback to read the latest history timestamp for a setting key.
HistoryReader = Callable[[str], str | None]


class SettingEncryptionService:
    """Handles encryption/decryption/redaction of ops setting values."""

    def __init__(self, encryption_key: str) -> None:
        self._encryption_key = encryption_key
        self._enabled = bool(encryption_key.strip())

    def is_encrypted_key(self, setting_key: str) -> bool:
        """Check if a setting key should be encrypted."""
        return setting_key in ENCRYPTED_SETTING_KEYS

    def encrypt_if_needed(self, setting_key: str, value: Any) -> Any:
        """Encrypt value if the key is in ENCRYPTED_SETTING_KEYS and encryption is enabled."""
        if not self.is_encrypted_key(setting_key):
            return value

        if value is None or value == "":
            return value

        if not self._enabled:
            raise SettingEncryptionError(
                "ops_settings_encryption_key is required to write encrypted setting "
                f"{setting_key!r}; a non-empty value cannot be stored plaintext"
            )

        # Convert value to string for encryption
        if isinstance(value, (dict, list)):
            import json

            plaintext = json.dumps(value, separators=(",", ":"))
        else:
            plaintext = str(value)

        return encrypt_setting_value(plaintext, self._encryption_key)

    def redact_value(self, setting_key: str, value: Any) -> Any:
        """Redact value for encrypted settings in history/audit.

        Only redacts if encryption is enabled and the stored value is actually
        encrypted. Plaintext values (written before encryption was enabled) are
        not redacted to avoid confusion - they remain visible in history.
        """
        if not self._enabled or not self.is_encrypted_key(setting_key):
            return value

        if value is None:
            return None

        # Check if it's already encrypted
        if isinstance(value, str) and is_encrypted_value(value):
            return "[REDACTED]"

        # Plaintext value for an encrypted key - don't redact, show as-is
        # This handles the migration case where a value was written before
        # encryption was enabled
        return value

    def get_masked_status(
        self,
        setting_key: str,
        source: str,
        db_value: Any | None = None,
        history_reader: HistoryReader | None = None,
    ) -> str:
        """Return masked status for encrypted settings.

        Returns one of:
        - "configured from environment"
        - "configured from dashboard, set <ISO date>"
        - "missing"

        Returns "" when encryption is not enabled or key is not an encrypted key.
        """
        if not self._enabled or not self.is_encrypted_key(setting_key):
            return ""

        # Check if there's a database override (dashboard-configured)
        if db_value is not None and db_value != "":
            if history_reader is not None:
                ts = history_reader(setting_key)
                if ts is not None:
                    return f"configured from dashboard, set {ts}"
            return "configured from dashboard"

        # Check if there's an environment value
        # The resolver is in the facade, so callers pass it via env_value
        return "missing"

    def get_masked_status_with_resolver(
        self,
        setting_key: str,
        source: str,
        resolver: Any,
        db_value: Any | None = None,
        history_reader: HistoryReader | None = None,
    ) -> str:
        """Return masked status using resolver to check environment.

        Returns "" when encryption is not enabled or key is not an encrypted key.
        """
        if not self._enabled or not self.is_encrypted_key(setting_key):
            return ""

        # Check if there's a database override (dashboard-configured)
        if db_value is not None and db_value != "":
            if history_reader is not None:
                ts = history_reader(setting_key)
                if ts is not None:
                    return f"configured from dashboard, set {ts}"
            return "configured from dashboard"

        # Check if there's an environment value
        env_val, _ = resolver._get_from_env_or_default(setting_key)
        if env_val is not None and env_val != "":
            return "configured from environment"

        return "missing"
