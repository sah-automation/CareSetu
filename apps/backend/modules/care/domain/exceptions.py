"""MOD-006: domain errors for the ``care`` module (coding-standards §3).

The hierarchy grows with the tickets that introduce real validation.
"""

from __future__ import annotations


class CareError(Exception):
    """Base error for the care module."""


class IllegalCareTransitionError(CareError):
    """Raised when a care case is asked to take an illegal lifecycle action.

    Mirrors :class:`~modules.intake.domain.exceptions.IllegalIntakeTransitionError`
    for the MOD-006 case machine (PHASE-8 T02, ticket #418): the case stage
    machine is a closed automaton, so every edge outside the binding transition
    table is reported with the action and the current stage named.
    """
