"""MOD-001: domain errors for the ``iam`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class IamError(Exception):
    """Base error for the iam module."""


class SmsDeliveryError(IamError):
    """An EXT-001 SMS delivery failed after the retry budget was exhausted.

    Raised by the provider adapter only; the mock never raises. The message is
    safe for logs - it never carries the OTP, the API key, or the raw payload.
    """
