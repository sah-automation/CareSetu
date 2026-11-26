"""MOD-005: domain errors for the ``intake`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class IntakeError(Exception):
    """Base error for the intake module."""


class IllegalIntakeTransitionError(IntakeError):
    """The attempted intake lifecycle action is illegal in the current status.

    Raised by the pure state machine for every edge outside the binding
    transition table - which is how the re-record attempt cap and forced-text
    paths are structurally enforced.
    """


class IllegalPreSummaryTransitionError(IntakeError):
    """The attempted pre-summary lifecycle action is illegal in the current state.

    Raised when a ``finalize`` or ``review`` action is applied outside the
    binding three-state machine (Draft -> Reviewed -> Final, ADR-0001).
    The low_confidence derived flag forces review before Final: an unreviewed
    low-confidence pre-summary cannot be finalized (the hard usage gate).
    """


class IntakeNotFoundError(IntakeError):
    """The requested intake does not exist or the caller does not own it.

    Raised by ``get_intake`` and ``get_pre_summary`` when no row matches the
    given intake id + patient id pair (spec #344: patient-scoped reads).
    """


class IntakeValidationError(IntakeError):
    """A submit_intake request failed server-side validation.

    Covers one-mode-per-intake enforcement and the text cap
    (``MAX_TEXT_LENGTH`` = 2000 chars). The message carries the specific
    failure reason so the route layer maps it to a typed error envelope.
    The voice-attempt cap (3 attempts) is enforced by the domain state
    machine at the re-record seam, not by this class.
    """


class MediaTransferError(IntakeError):
    """An intake-media upload exhausted every retry and was never captured.

    Raised by ``upload_intake_media`` after the underlying object-store write
    failed on all three upload-resilience attempts (NFR-PERF-002, spec #344).
    This is the typed guarantee that a partial capture is never silently lost:
    the caller either gets a durable media ref, or this typed error tells them
    the transfer failed and the clip was not stored.
    """
