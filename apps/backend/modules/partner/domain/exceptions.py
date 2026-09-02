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


class PartnerNotRejectedError(PartnerError):
    """The recovery action requires the partner to be in the ``[Rejected]`` state.

    A rejection-reason view or a one-time appeal only makes sense for a rejected
    partner (ADR-0008 recovery; PHASE-5 T09). Raising from the domain core keeps
    the precondition in the facade, never just the router.
    """

    def __init__(self, partner_id: int, status: str) -> None:
        super().__init__(
            f"partner {partner_id} is {status}; rejection recovery requires 'Rejected'"
        )
        self.partner_id = partner_id
        self.status = status


class AppealAlreadyUsedError(PartnerError):
    """The partner's one-time appeal has already been consumed (PHASE-5 T09).

    A rejection appeal may be filed exactly once; a second attempt is rejected
    (the ``appeal_used`` flag is consumed on first use and never re-armed).
    """


class ServiceAreaNotFoundError(PartnerError):
    """The ``service_area_id`` a registration declared does not exist (PHASE-5 #265).

    A partner can never be attached to a nonexistent service area: an unknown
    ``service_area_id`` is rejected (mapped to a 422) instead of silently
    persisting a dangling reference.
    """

    def __init__(self, service_area_id: int) -> None:
        super().__init__(f"no service area exists with id {service_area_id}")
        self.service_area_id = service_area_id


class ReSubmissionThrottledError(PartnerError):
    """A rejected partner has exhausted the re-submission budget (PHASE-5 T09).

    The verification queue is protected by a business-rule throttle - a rejected
    partner may re-submit corrected credentials up to a maximum number of rounds
    before a cooldown (NFR-001 headcount, ADR-0008). Raised when the boundary is
    crossed so the queue cannot be spammed.
    """

    def __init__(self, partner_id: int, retry_at: str | None = None) -> None:
        message = f"partner {partner_id} has exceeded the re-submission limit"
        if retry_at is not None:
            message += f"; retry after {retry_at}"
        super().__init__(message)
        self.partner_id = partner_id
        self.retry_at = retry_at
