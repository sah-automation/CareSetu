"""MOD-002: domain errors for the ``partner`` module (coding-standards §3).

Phase 1 carries the module base error only; the hierarchy grows
with the tickets that introduce real validation.
"""

from __future__ import annotations


class PartnerError(Exception):
    """Base error for the partner module."""


class IllegalPartnerTransitionError(PartnerError):
    """The attempted lifecycle action is illegal in the profile's current state.

    Raised by the pure state machine for arbitrary inputs - including any path
    that would reach ``Active`` without an explicit operator approval, or a
    Step-1 auto-fail that would enter the operator queue (ADR-0008, ticket #247).
    """


class PartnerNotFoundError(PartnerError):
    """No partner profile exists under the addressed id."""

    def __init__(self, partner_id: int) -> None:
        super().__init__(f"no partner exists with id {partner_id}")
        self.partner_id = partner_id
