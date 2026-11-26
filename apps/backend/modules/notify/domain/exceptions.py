"""MOD-010: domain errors for the ``notify`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class NotifyError(Exception):
    """Base error for the notify module."""


class NotificationDeliveryError(NotifyError):
    """A delivery channel (WhatsApp EXT-003 or SMS EXT-001) failed to deliver.

    Raised by the provider adapters only; the mocks never raise. The message
    is safe for logs - it never carries the API key, the raw payload, or any
    content. ``retries_exhausted`` distinguishes the retry-exhaustion failure
    (True) from a rejection or response-shape failure the provider gives up on
    without retrying (False); the ``notification.failed`` signal fires only for
    the former (ADR-0009).
    """

    def __init__(self, message: str, *, retries_exhausted: bool = True) -> None:
        super().__init__(message)
        self.retries_exhausted = retries_exhausted
