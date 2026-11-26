"""MOD-002: the pure partner lifecycle state machine (PHASE-5 T04, ticket #247).

The binding, two-step-gate machine ratified in ADR-0008 (and spec phase-5
"Implementation decisions"):

    [Registered] -> [Under Verification] -> [Active] | [Rejected]
                        |                         |
      Step-1 auto-fail  +-- operator approve      +- re-verification (7-day grace)
      (never queued)        operator reject       |- window lapses -> Under Verification
                                                 +-- operator reject -> [Rejected]

The no-auto-approve guarantee falls straight out of the transition table:
``Active`` is reachable ONLY from ``Under Verification`` via
:attr:`PartnerAction.OPERATOR_APPROVE` - the explicit, individually-attributed
operator decision (ADR-0008 §2). Neither Step-1 (:attr:`PartnerAction.AUTO_FAIL`)
nor opening a round (:attr:`PartnerAction.START_VERIFICATION`) ever produces
``Active``, so an automated check can never grant activation.

Verification rounds: ``round`` counts the verification rounds opened on the
partner (1 = first-time, increments on every re-submission / re-verification).
A credentials pass opens round ``round+1``; a Step-1 auto-fail is a pre-filter
rejection that never enters the operator queue and opens no round. An ``Active``
partner who re-submits stays ``Active`` through the 7-day grace window (round
increments); only an explicit operator reject or a lapsed window
(:attr:`PartnerAction.GRACE_LAPSE`) moves them off ``Active``.

Pure decision logic only: no schema, facade or adapter imports - the
persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.partner.domain.exceptions import IllegalPartnerTransitionError


class PartnerStatus(StrEnum):
    """The partner profile lifecycle status (mirrors ``partner_profiles.status``)."""

    REGISTERED = "Registered"
    UNDER_VERIFICATION = "Under Verification"
    ACTIVE = "Active"
    REJECTED = "Rejected"


class PartnerAction(StrEnum):
    """The lifecycle actions a partner profile can be asked to take."""

    # A credentials submission that passes Step-1: opens the next verification
    # round and (re)enters the operator queue.
    START_VERIFICATION = "start_verification"
    # Step-1 auto-fail: format/duplicate validation failed - reject, never queued.
    AUTO_FAIL = "auto_fail"
    # Step-2 manual activation gate: explicit operator approval only.
    OPERATOR_APPROVE = "operator_approve"
    # Step-2 manual decision: operator reject (with reason).
    OPERATOR_REJECT = "operator_reject"
    # An Active partner's 7-day grace window lapsed without a decision.
    GRACE_LAPSE = "grace_lapse"


@dataclass(frozen=True)
class PartnerState:
    """One immutable snapshot of a partner's lifecycle.

    ``round`` counts the verification rounds opened (0 = never verified).
    """

    status: PartnerStatus
    round: int


REGISTERED: PartnerState = PartnerState(status=PartnerStatus.REGISTERED, round=0)

#: ``(status, action)`` -> ``(target status, round delta)``. ``round_delta`` is
#: 1 when the action opens a new verification round, else 0.
_LEGAL_TRANSITIONS: dict[tuple[PartnerStatus, PartnerAction], tuple[PartnerStatus, int]] = {
    # Fresh (or re-submitted) credentials that pass Step-1 open the next round
    # and (re)enter the operator queue; an Under-Verification partner can also
    # open a further round on re-submission.
    (PartnerStatus.REGISTERED, PartnerAction.START_VERIFICATION): (
        PartnerStatus.UNDER_VERIFICATION,
        1,
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.START_VERIFICATION): (
        PartnerStatus.UNDER_VERIFICATION,
        1,
    ),
    (PartnerStatus.REJECTED, PartnerAction.START_VERIFICATION): (
        PartnerStatus.UNDER_VERIFICATION,
        1,
    ),
    # An Active partner re-submitting stays Active through the 7-day grace
    # window; the round increments for the re-verification trail.
    (PartnerStatus.ACTIVE, PartnerAction.START_VERIFICATION): (PartnerStatus.ACTIVE, 1),
    # Step-1 auto-fail is a pre-filter rejection, never queued: no round opens.
    (PartnerStatus.REGISTERED, PartnerAction.AUTO_FAIL): (PartnerStatus.REJECTED, 0),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.AUTO_FAIL): (
        PartnerStatus.REJECTED,
        0,
    ),
    # Step-2 manual gate. Active is reachable ONLY from Under Verification here.
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.OPERATOR_APPROVE): (
        PartnerStatus.ACTIVE,
        0,
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.OPERATOR_REJECT): (
        PartnerStatus.REJECTED,
        0,
    ),
    # Re-verification decisions on an Active partner: approve = no disruption
    # (stays Active), reject = terminal failure.
    (PartnerStatus.ACTIVE, PartnerAction.OPERATOR_APPROVE): (PartnerStatus.ACTIVE, 0),
    (PartnerStatus.ACTIVE, PartnerAction.OPERATOR_REJECT): (PartnerStatus.REJECTED, 0),
    # Grace window lapsing without a decision auto-drops Active to Under Verification.
    (PartnerStatus.ACTIVE, PartnerAction.GRACE_LAPSE): (PartnerStatus.UNDER_VERIFICATION, 0),
}


def transition(state: PartnerState, action: PartnerAction) -> PartnerState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    Raises :class:`IllegalPartnerTransitionError` for every edge outside the
    binding machine - which is exactly how the no-auto-approve and never-queued
    guarantees are enforced: an unknown edge cannot sneak a partner into
    ``Active`` or a Step-1 failure into the operator queue.
    """
    edge = _LEGAL_TRANSITIONS.get((state.status, action))
    if edge is None:
        raise IllegalPartnerTransitionError(
            f"{action.value} is illegal while the partner is {state.status.value}"
        )
    next_status, round_delta = edge
    return PartnerState(status=next_status, round=state.round + round_delta)
