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
