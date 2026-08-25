"""PHASE-3 T3: consent state-machine transition legality (ticket #212, FEAT-002).

The machine is a pure decision, so the unit suite pins the whole
status x action matrix without a database (prior art: the IAM lockout
domain tests). The binding diagram from spec #209 is exercised edge by
edge, and every edge OUTSIDE it is rejected for arbitrary inputs - the
parametrized sweep proves an un-revoked terminal version can never be
reused and nothing at all happens to a closed request.
"""

from __future__ import annotations

import pytest

from modules.consent.domain.exceptions import IllegalConsentTransitionError
from modules.consent.domain.state_machine import (
    REQUESTED,
    ConsentAction,
    ConsentState,
    ConsentStatus,
    transition,
)

_V2_GRANTED = ConsentState(ConsentStatus.GRANTED, version=2)
_V2_REVOKED = ConsentState(ConsentStatus.REVOKED, version=2)
_DECLINED = ConsentState(ConsentStatus.DECLINED, version=0)


def test_fresh_request_starts_at_version_zero() -> None:
    assert REQUESTED.status is ConsentStatus.REQUESTED
    assert REQUESTED.version == 0


def test_granting_a_request_mints_version_one() -> None:
    granted = transition(REQUESTED, ConsentAction.GRANT)

    assert granted == ConsentState(ConsentStatus.GRANTED, version=1)


def test_regrant_of_a_live_grant_mints_the_next_version() -> None:
    granted = transition(_V2_GRANTED, ConsentAction.GRANT)

    assert granted == ConsentState(ConsentStatus.GRANTED, version=3)


def test_revocation_is_terminal_for_that_version() -> None:
    revoked = transition(_V2_GRANTED, ConsentAction.REVOKE)

    assert revoked.status is ConsentStatus.REVOKED
    # The revoked version keeps its number: receipts citing v2 stay exact.
    assert revoked.version == 2


def test_regrant_after_revocation_continues_the_lineage() -> None:
    granted = transition(_V2_REVOKED, ConsentAction.GRANT)

    assert granted == ConsentState(ConsentStatus.GRANTED, version=3)


def test_decline_closes_a_request_without_creating_a_grant() -> None:
    declined = transition(REQUESTED, ConsentAction.DECLINE)

    assert declined.status is ConsentStatus.DECLINED
    assert declined.version == 0


def test_explicit_grant_after_a_decline_starts_the_lineage_at_v1() -> None:
    # The unique lineage key leaves one row per triple; a fresh grant after a
    # decline revives it with its FIRST version, never a phantom re-grant.
    granted = transition(_DECLINED, ConsentAction.GRANT)

    assert granted == ConsentState(ConsentStatus.GRANTED, version=1)


def test_transition_returns_new_immutable_states() -> None:
    # Versions are immutable once written: applying an action must never
    # mutate the state it was given.
    snapshot = ConsentState(ConsentStatus.GRANTED, version=7)

    transition(snapshot, ConsentAction.REVOKE)

    assert snapshot == ConsentState(ConsentStatus.GRANTED, version=7)


_LEGAL_EDGES: dict[tuple[ConsentStatus, ConsentAction], ConsentState] = {
    (ConsentStatus.REQUESTED, ConsentAction.GRANT): ConsentState(ConsentStatus.GRANTED, version=1),
    (ConsentStatus.REQUESTED, ConsentAction.DECLINE): _DECLINED,
    (ConsentStatus.GRANTED, ConsentAction.GRANT): ConsentState(ConsentStatus.GRANTED, version=3),
    (ConsentStatus.GRANTED, ConsentAction.REVOKE): ConsentState(ConsentStatus.REVOKED, version=2),
    (ConsentStatus.REVOKED, ConsentAction.GRANT): ConsentState(ConsentStatus.GRANTED, version=3),
    (ConsentStatus.DECLINED, ConsentAction.GRANT): ConsentState(ConsentStatus.GRANTED, version=1),
}

_ALL_STATUSES = (
    ConsentStatus.REQUESTED,
    ConsentStatus.GRANTED,
    ConsentStatus.REVOKED,
    ConsentStatus.DECLINED,
)

_ALL_ACTIONS = (ConsentAction.GRANT, ConsentAction.REVOKE, ConsentAction.DECLINE)


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_matches_the_binding_machine(
    status: ConsentStatus, action: ConsentAction
) -> None:
    # Version 2 exercises the "versions are immutable once terminal" rule:
    # a revoked v2 must refuse revoke again rather than rewind or bump.
    state = ConsentState(
        status, version=2 if status in (_V2_GRANTED.status, _V2_REVOKED.status) else 0
    )
    expected = _LEGAL_EDGES.get((status, action))

    if expected is None:
        with pytest.raises(IllegalConsentTransitionError):
            transition(state, action)
    else:
        assert transition(state, action) == expected


def test_illegal_message_names_the_action_and_state() -> None:
    with pytest.raises(IllegalConsentTransitionError, match=r"revoke.*requested"):
        transition(REQUESTED, ConsentAction.REVOKE)
