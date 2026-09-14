"""MOD-006: domain errors for the ``care`` module (coding-standards §3).

The hierarchy grows with the tickets that introduce real validation.
"""

from __future__ import annotations


class CareError(Exception):
    """Base error for the care module."""


class CareNotFoundError(CareError):
    """Raised when a care entity is not found or the caller lacks access.

    Mirrors :class:`~modules.intake.domain.exceptions.IntakeNotFoundError`
    for the MOD-006 care module (PHASE-8 T04, ticket #420): the facade
    raises this when a care case lookup misses, or when the requesting
    doctor does not own the case.
    """


class CareValidationError(CareError):
    """Raised when a care write is rejected by a state/input validation.

    Mirrors :class:`~modules.intake.domain.exceptions.IntakeValidationError`
    for the MOD-006 care module (PHASE-8 T04, ticket #420): raised for a
    non-transition state or input check the case machine does not decide
    (e.g. a closed case rejecting a fresh doctor input).
    """


class IllegalCareTransitionError(CareError):
    """Raised when a care case is asked to take an illegal lifecycle action.

    Mirrors :class:`~modules.intake.domain.exceptions.IllegalIntakeTransitionError`
    for the MOD-006 case machine (PHASE-8 T02, ticket #418): the case stage
    machine is a closed automaton, so every edge outside the binding transition
    table is reported with the action and the current stage named.
    """


class IllegalPrescriptionTransitionError(CareError):
    """Raised when a prescription is asked to take an illegal lifecycle action.

    Mirrors :class:`~modules.intake.domain.exceptions.IllegalPreSummaryTransitionError`
    for the MOD-006 prescription machine (PHASE-8 T03, ticket #419): the
    prescription machine is a closed automaton, so every edge outside the
    binding transition table is reported with the action, current status, and
    any missing transition prerequisite (verification declaration, rejection
    reason, or the drafting cap) named. ``CareError`` subclasses carry the
    ``care`` module's namespace so the facade can map them to typed responses.
    """
