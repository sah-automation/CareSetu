"""MOD-014: domain errors for the ``ops`` module (coding-standards §3).

#764 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class OpsError(Exception):
    """Base error for the ops module."""


class InvalidFeatureFlagWriteError(OpsError):
    """Raised when a feature flag write is not allowed."""

    def __init__(self, flag_key: str, reason: str) -> None:
        super().__init__(f"Feature flag '{flag_key}' write not allowed: {reason}")
        self.flag_key = flag_key
        self.reason = reason


class InvalidSettingWriteError(OpsError):
    """Raised when a setting write is not allowed."""

    def __init__(self, setting_key: str, reason: str) -> None:
        super().__init__(f"Setting '{setting_key}' write not allowed: {reason}")
        self.setting_key = setting_key
        self.reason = reason
