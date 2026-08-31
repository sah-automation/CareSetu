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


class InvalidQueueSortError(PartnerError):
    """The operator asked to sort the verification queue by an unknown key."""

    def __init__(self, sort_by: str) -> None:
        super().__init__(f"unknown verification queue sort key: {sort_by}")
        self.sort_by = sort_by


class RejectionReasonRequiredError(PartnerError):
    """An operator rejection must carry a reason (two-step gate, ADR-0008).

    Moves the reject-requires-reason invariant into the domain core so no
    adapter or future caller can reject without explaining why (coding-standards
    §4: pre-conditions live in the domain core, never in the router).
    """
