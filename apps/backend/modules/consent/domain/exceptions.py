"""MOD-004: domain errors for the ``consent`` module (coding-standards §3).

The hierarchy grows with the tickets that introduce real validation;
every error maps to a shared-envelope code at the route adapter.
"""

from __future__ import annotations


class ConsentError(Exception):
    """Base error for the consent module."""


class IllegalConsentTransitionError(ConsentError):
    """The attempted lifecycle action is illegal in the row's current state.

    Raised by the pure state machine for arbitrary inputs and surfaced by
    the routes as ``409 CONSENT_INVALID_TRANSITION`` - the binding machine
    admits exactly the ratified edges (ticket #212).
    """


class ConsentNotFoundError(ConsentError):
    """No consent lineage exists under the addressed id for this patient."""

    def __init__(self, consent_id: int) -> None:
        super().__init__(f"no consent exists with id {consent_id}")
        self.consent_id = consent_id


class ConsentAccessDeniedError(ConsentError):
    """The caller is not the patient who owns this consent lineage."""
