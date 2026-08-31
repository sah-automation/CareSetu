"""PHASE-5 T04: partner lifecycle state-machine transition legality (ticket #247).

The machine is a pure decision (ADR-0008 two-step gate), so the unit suite
pins the whole status x action matrix without a database (prior art: the
consent and IAM lockout domain tests). The binding diagram from spec phase-5
"Partner lifecycle state machine" is exercised edge by edge, and every edge
OUTSIDE it is rejected - which is exactly how the two hard guarantees are
enforced: no auto-approve (``Active`` reachable only via operator approval) and
no queued Step-1 failure (``AUTO_FAIL`` rejects, never enters the operator
queue).
"""

from __future__ import annotations

import pytest

from modules.partner.domain.exceptions import IllegalPartnerTransitionError
from modules.partner.domain.state_machine import (
    REGISTERED,
    PartnerAction,
    PartnerState,
    PartnerStatus,
    transition,
)

_REGISTERED = PartnerState(PartnerStatus.REGISTERED, round=0)
_UNDER_VERIFICATION = PartnerState(PartnerStatus.UNDER_VERIFICATION, round=1)
_ACTIVE = PartnerState(PartnerStatus.ACTIVE, round=1)
_REJECTED = PartnerState(PartnerStatus.REJECTED, round=1)


def test_fresh_partner_starts_registered_round_zero() -> None:
    assert REGISTERED.status is PartnerStatus.REGISTERED
    assert REGISTERED.round == 0


def test_step1_pass_opens_first_round_into_under_verification() -> None:
    next_state = transition(_REGISTERED, PartnerAction.START_VERIFICATION)

    assert next_state.status is PartnerStatus.UNDER_VERIFICATION
    assert next_state.round == 1


def test_step1_fail_rejects_never_queued() -> None:
    # AUTO_FAIL is a pre-filter rejection: it lands the partner in Rejected and
    # opens NO verification round - it must never appear in the operator queue.
    next_state = transition(_REGISTERED, PartnerAction.AUTO_FAIL)

    assert next_state.status is PartnerStatus.REJECTED
    assert next_state.round == 0


def test_operator_reject_rejects_with_terminal_status() -> None:
    next_state = transition(_UNDER_VERIFICATION, PartnerAction.OPERATOR_REJECT)

    assert next_state.status is PartnerStatus.REJECTED


def test_operator_approve_is_the_only_path_to_active() -> None:
    next_state = transition(_UNDER_VERIFICATION, PartnerAction.OPERATOR_APPROVE)

    assert next_state.status is PartnerStatus.ACTIVE


def test_step1_pass_alone_never_yields_active() -> None:
    # The no-auto-approve guarantee: a Step-1 pass advances to Under
    # Verification, never Active - an automated check cannot grant activation.
    after_pass = transition(_REGISTERED, PartnerAction.START_VERIFICATION)
    assert after_pass.status is PartnerStatus.UNDER_VERIFICATION
    # ...and repeating Step-1 passes cannot climb to Active either.
    again = transition(after_pass, PartnerAction.START_VERIFICATION)
    assert again.status is PartnerStatus.UNDER_VERIFICATION
    assert again.round == 2


def test_step1_fail_never_yields_active() -> None:
    for state in (_REGISTERED, _UNDER_VERIFICATION):
        result = transition(state, PartnerAction.AUTO_FAIL)
        assert result.status is PartnerStatus.REJECTED


def test_re_submission_from_rejected_opens_a_new_round() -> None:
    next_state = transition(_REJECTED, PartnerAction.START_VERIFICATION)

    assert next_state.status is PartnerStatus.UNDER_VERIFICATION
    assert next_state.round == 2


def test_reverification_keeps_active_through_grace_round_increments() -> None:
    # An Active partner re-submitting stays Active through the 7-day grace
    # window; the round increments so the re-verification is distinguishable.
    next_state = transition(_ACTIVE, PartnerAction.START_VERIFICATION)

    assert next_state.status is PartnerStatus.ACTIVE
    assert next_state.round == 2


def test_reverification_success_keeps_active() -> None:
    next_state = transition(_ACTIVE, PartnerAction.OPERATOR_APPROVE)

    assert next_state.status is PartnerStatus.ACTIVE


def test_reverification_failure_rejects() -> None:
    next_state = transition(_ACTIVE, PartnerAction.OPERATOR_REJECT)

    assert next_state.status is PartnerStatus.REJECTED


def test_grace_window_lapse_drops_active_to_under_verification() -> None:
    next_state = transition(_ACTIVE, PartnerAction.GRACE_LAPSE)

    assert next_state.status is PartnerStatus.UNDER_VERIFICATION


def test_transition_returns_new_immutable_states() -> None:
    snapshot = PartnerState(PartnerStatus.UNDER_VERIFICATION, round=3)

    transition(snapshot, PartnerAction.OPERATOR_APPROVE)

    assert snapshot == PartnerState(PartnerStatus.UNDER_VERIFICATION, round=3)


_LEGAL_EDGES: dict[tuple[PartnerStatus, PartnerAction], PartnerState] = {
    (PartnerStatus.REGISTERED, PartnerAction.START_VERIFICATION): PartnerState(
        PartnerStatus.UNDER_VERIFICATION, round=1
    ),
    (PartnerStatus.REGISTERED, PartnerAction.AUTO_FAIL): PartnerState(
        PartnerStatus.REJECTED, round=0
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.START_VERIFICATION): PartnerState(
        PartnerStatus.UNDER_VERIFICATION, round=2
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.AUTO_FAIL): PartnerState(
        PartnerStatus.REJECTED, round=1
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.OPERATOR_APPROVE): PartnerState(
        PartnerStatus.ACTIVE, round=1
    ),
    (PartnerStatus.UNDER_VERIFICATION, PartnerAction.OPERATOR_REJECT): PartnerState(
        PartnerStatus.REJECTED, round=1
    ),
    (PartnerStatus.ACTIVE, PartnerAction.START_VERIFICATION): PartnerState(
        PartnerStatus.ACTIVE, round=2
    ),
    (PartnerStatus.ACTIVE, PartnerAction.OPERATOR_APPROVE): PartnerState(
        PartnerStatus.ACTIVE, round=1
    ),
    (PartnerStatus.ACTIVE, PartnerAction.OPERATOR_REJECT): PartnerState(
        PartnerStatus.REJECTED, round=1
    ),
    (PartnerStatus.ACTIVE, PartnerAction.GRACE_LAPSE): PartnerState(
        PartnerStatus.UNDER_VERIFICATION, round=1
    ),
    (PartnerStatus.REJECTED, PartnerAction.START_VERIFICATION): PartnerState(
        PartnerStatus.UNDER_VERIFICATION, round=2
    ),
}

_ALL_STATUSES = (
    PartnerStatus.REGISTERED,
    PartnerStatus.UNDER_VERIFICATION,
    PartnerStatus.ACTIVE,
    PartnerStatus.REJECTED,
)

_ALL_ACTIONS = (
    PartnerAction.START_VERIFICATION,
    PartnerAction.AUTO_FAIL,
    PartnerAction.OPERATOR_APPROVE,
    PartnerAction.OPERATOR_REJECT,
    PartnerAction.GRACE_LAPSE,
)


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_matches_the_binding_machine(
    status: PartnerStatus, action: PartnerAction
) -> None:
    # Round 1 for every status except fresh Registered (round 0) exercises the
    # round arithmetic against the binding table.
    state = PartnerState(status, round=0 if status is PartnerStatus.REGISTERED else 1)
    expected = _LEGAL_EDGES.get((status, action))

    if expected is None:
        with pytest.raises(IllegalPartnerTransitionError):
            transition(state, action)
    else:
        assert transition(state, action) == expected


def test_illegal_message_names_the_action_and_state() -> None:
    with pytest.raises(IllegalPartnerTransitionError, match=r"operator_approve.*Registered"):
        transition(REGISTERED, PartnerAction.OPERATOR_APPROVE)


def test_operator_cannot_auto_approve_a_registered_partner() -> None:
    # No short-circuit from Registered to Active: the machine has no edge for
    # an approval before Step 1, so the no-auto-approve guarantee holds end to
    # end even against a malformed caller.
    with pytest.raises(IllegalPartnerTransitionError):
        transition(REGISTERED, PartnerAction.OPERATOR_APPROVE)
