"""PHASE-7 T02: intake lifecycle state-machine transition legality (ticket #346).

The machine is a pure decision (no I/O, no schema imports), so the unit suite
pins the full status x action matrix without a database. Every edge in the
binding diagram is exercised, the re-record attempt cap and forced-text path
are boundary-tested, and every illegal transition raises the typed
:class:`IllegalIntakeTransitionError`.
"""

from __future__ import annotations

import pytest

from modules.intake.domain.exceptions import IllegalIntakeTransitionError
from modules.intake.domain.state_machine import (
    CAPTURED,
    MAX_RECORD_ATTEMPTS,
    PARTIAL_MIN_CHARS,
    USABLE_MIN_CHARS,
    IntakeAction,
    IntakeState,
    IntakeStatus,
    classify_transcript_usability,
    transition,
)

_CAPTURED_1 = IntakeState(IntakeStatus.CAPTURED, record_attempts=1, forced_text=False)
_STRUCTURING_1 = IntakeState(IntakeStatus.STRUCTURING, record_attempts=1, forced_text=False)
_STRUCTURING_2 = IntakeState(IntakeStatus.STRUCTURING, record_attempts=2, forced_text=False)
_STRUCTURING_3 = IntakeState(IntakeStatus.STRUCTURING, record_attempts=3, forced_text=False)
_RE_RECORD_1 = IntakeState(IntakeStatus.RE_RECORD, record_attempts=1, forced_text=False)
_RE_RECORD_2 = IntakeState(IntakeStatus.RE_RECORD, record_attempts=2, forced_text=False)
_READY_1 = IntakeState(IntakeStatus.READY_FOR_REVIEW, record_attempts=1, forced_text=False)
_FAILED_1 = IntakeState(IntakeStatus.FAILED, record_attempts=1, forced_text=False)


def test_fresh_intake_starts_captured_attempt_one() -> None:
    assert CAPTURED.status is IntakeStatus.CAPTURED
    assert CAPTURED.record_attempts == 1
    assert CAPTURED.forced_text is False


def test_start_structuring_moves_captured_to_structuring() -> None:
    next_state = transition(_CAPTURED_1, IntakeAction.START_STRUCTURING)

    assert next_state.status is IntakeStatus.STRUCTURING
    assert next_state.record_attempts == 1
    assert next_state.forced_text is False


def test_structuring_success_produces_ready_for_review() -> None:
    next_state = transition(_STRUCTURING_1, IntakeAction.STRUCTURING_SUCCESS)

    assert next_state.status is IntakeStatus.READY_FOR_REVIEW
    assert next_state.forced_text is False


def test_raw_text_fallback_produces_ready_for_review() -> None:
    next_state = transition(_STRUCTURING_1, IntakeAction.RAW_TEXT)

    assert next_state.status is IntakeStatus.READY_FOR_REVIEW
    assert next_state.forced_text is False


def test_record_unusable_with_attempts_remaining_moves_to_re_record() -> None:
    next_state = transition(_STRUCTURING_1, IntakeAction.RECORD_UNUSABLE)

    assert next_state.status is IntakeStatus.RE_RECORD
    assert next_state.record_attempts == 1
    assert next_state.forced_text is False


def test_retry_accepted_increments_attempt_and_returns_to_structuring() -> None:
    next_state = transition(_RE_RECORD_1, IntakeAction.RETRY_ACCEPTED)

    assert next_state.status is IntakeStatus.STRUCTURING
    assert next_state.record_attempts == 2
    assert next_state.forced_text is False


def test_record_unusable_at_cap_forces_text() -> None:
    next_state = transition(_STRUCTURING_3, IntakeAction.RECORD_UNUSABLE)

    assert next_state.status is IntakeStatus.READY_FOR_REVIEW
    assert next_state.record_attempts == 3
    assert next_state.forced_text is True


def test_force_text_from_re_record_sets_forced_text() -> None:
    next_state = transition(_RE_RECORD_2, IntakeAction.FORCE_TEXT)

    assert next_state.status is IntakeStatus.READY_FOR_REVIEW
    assert next_state.forced_text is True


def test_fail_from_structuring_yields_failed() -> None:
    next_state = transition(_STRUCTURING_1, IntakeAction.FAIL)

    assert next_state.status is IntakeStatus.FAILED
    assert next_state.record_attempts == 1


def test_fail_from_re_record_yields_failed() -> None:
    next_state = transition(_RE_RECORD_1, IntakeAction.FAIL)

    assert next_state.status is IntakeStatus.FAILED


def test_structuring_success_preserves_existing_forced_text() -> None:
    state = IntakeState(IntakeStatus.STRUCTURING, record_attempts=2, forced_text=True)

    next_state = transition(state, IntakeAction.STRUCTURING_SUCCESS)

    assert next_state.status is IntakeStatus.READY_FOR_REVIEW
    assert next_state.forced_text is True


def test_full_b3_ladder_exactly_three_attempts() -> None:
    """Exercise the B3 fallback ladder: attempts 1, 2, 3 then forced text."""
    # Start and enter structuring on attempt 1.
    s = transition(_CAPTURED_1, IntakeAction.START_STRUCTURING)
    assert s.status is IntakeStatus.STRUCTURING

    # Audio unusable, attempt 1 < 3 -> re-record.
    s = transition(s, IntakeAction.RECORD_UNUSABLE)
    assert s.status is IntakeStatus.RE_RECORD
    assert s.record_attempts == 1

    # Retry accepted -> structuring attempt 2.
    s = transition(s, IntakeAction.RETRY_ACCEPTED)
    assert s.status is IntakeStatus.STRUCTURING
    assert s.record_attempts == 2

    # Audio unusable, attempt 2 < 3 -> re-record.
    s = transition(s, IntakeAction.RECORD_UNUSABLE)
    assert s.status is IntakeStatus.RE_RECORD
    assert s.record_attempts == 2

    # Retry accepted -> structuring attempt 3.
    s = transition(s, IntakeAction.RETRY_ACCEPTED)
    assert s.status is IntakeStatus.STRUCTURING
    assert s.record_attempts == 3

    # Audio unusable, attempt 3 >= cap -> forced text.
    s = transition(s, IntakeAction.RECORD_UNUSABLE)
    assert s.status is IntakeStatus.READY_FOR_REVIEW
    assert s.record_attempts == 3
    assert s.forced_text is True


def test_transition_returns_new_immutable_states() -> None:
    snapshot = IntakeState(IntakeStatus.STRUCTURING, record_attempts=2, forced_text=False)

    transition(snapshot, IntakeAction.STRUCTURING_SUCCESS)

    assert snapshot == IntakeState(IntakeStatus.STRUCTURING, record_attempts=2, forced_text=False)


def test_max_record_attempts_matches_spec() -> None:
    assert MAX_RECORD_ATTEMPTS == 3


# ---------------------------------------------------------------------------
# Exhaustive parametrised matrix
# ---------------------------------------------------------------------------

# Fixed (non-conditional) legal edges: (status, action) -> expected state
_LEGAL_EDGES: dict[tuple[IntakeStatus, IntakeAction], IntakeState] = {
    (IntakeStatus.CAPTURED, IntakeAction.START_STRUCTURING): IntakeState(
        IntakeStatus.STRUCTURING, record_attempts=1, forced_text=False
    ),
    (IntakeStatus.STRUCTURING, IntakeAction.STRUCTURING_SUCCESS): IntakeState(
        IntakeStatus.READY_FOR_REVIEW, record_attempts=1, forced_text=False
    ),
    (IntakeStatus.STRUCTURING, IntakeAction.RAW_TEXT): IntakeState(
        IntakeStatus.READY_FOR_REVIEW, record_attempts=1, forced_text=False
    ),
    (IntakeStatus.RE_RECORD, IntakeAction.RETRY_ACCEPTED): IntakeState(
        IntakeStatus.STRUCTURING, record_attempts=2, forced_text=False
    ),
    (IntakeStatus.RE_RECORD, IntakeAction.FORCE_TEXT): IntakeState(
        IntakeStatus.READY_FOR_REVIEW, record_attempts=1, forced_text=True
    ),
    (IntakeStatus.STRUCTURING, IntakeAction.FAIL): IntakeState(
        IntakeStatus.FAILED, record_attempts=1, forced_text=False
    ),
    (IntakeStatus.RE_RECORD, IntakeAction.FAIL): IntakeState(
        IntakeStatus.FAILED, record_attempts=1, forced_text=False
    ),
}

# RECORD_UNUSABLE from STRUCTURING has two outcomes depending on attempt cap,
# so it's tested separately from the flat matrix (see
# ``test_record_unusable_branches_on_attempt_cap``).

_ALL_STATUSES = (
    IntakeStatus.CAPTURED,
    IntakeStatus.STRUCTURING,
    IntakeStatus.READY_FOR_REVIEW,
    IntakeStatus.RE_RECORD,
    IntakeStatus.FAILED,
)

_ALL_ACTIONS = (
    IntakeAction.START_STRUCTURING,
    IntakeAction.STRUCTURING_SUCCESS,
    IntakeAction.RAW_TEXT,
    IntakeAction.RECORD_UNUSABLE,
    IntakeAction.RETRY_ACCEPTED,
    IntakeAction.FORCE_TEXT,
    IntakeAction.FAIL,
)


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_matches_the_binding_machine(
    status: IntakeStatus, action: IntakeAction
) -> None:
    # attempt 1 for most; attempt 1 for Captured (fresh).
    state = IntakeState(status, record_attempts=1, forced_text=False)
    expected = _LEGAL_EDGES.get((status, action))

    # RECORD_UNUSABLE from STRUCTURING is unfolded by attempt cap in
    # ``test_record_unusable_branches_on_attempt_cap``; from every other
    # status it is illegal.
    if action is IntakeAction.RECORD_UNUSABLE:
        if status is IntakeStatus.STRUCTURING:
            result = transition(state, action)
            assert result.status is IntakeStatus.RE_RECORD  # attempt 1 < cap
        else:
            with pytest.raises(IllegalIntakeTransitionError):
                transition(state, action)
        return

    if expected is None:
        with pytest.raises(IllegalIntakeTransitionError):
            transition(state, action)


def test_record_unusable_branches_on_attempt_cap() -> None:
    # attempt 1 (below cap) -> Re-record
    s_below = IntakeState(IntakeStatus.STRUCTURING, record_attempts=1, forced_text=False)
    result_below = transition(s_below, IntakeAction.RECORD_UNUSABLE)
    assert result_below.status is IntakeStatus.RE_RECORD
    assert result_below.record_attempts == 1

    # attempt 3 (at cap) -> forced text
    s_at = IntakeState(
        IntakeStatus.STRUCTURING, record_attempts=MAX_RECORD_ATTEMPTS, forced_text=False
    )
    result_at = transition(s_at, IntakeAction.RECORD_UNUSABLE)
    assert result_at.status is IntakeStatus.READY_FOR_REVIEW
    assert result_at.forced_text is True

    # attempt 2 (below cap) -> Re-record
    s_below2 = IntakeState(IntakeStatus.STRUCTURING, record_attempts=2, forced_text=False)
    result_below2 = transition(s_below2, IntakeAction.RECORD_UNUSABLE)
    assert result_below2.status is IntakeStatus.RE_RECORD
    assert result_below2.record_attempts == 2


def test_illegal_message_names_the_action_and_status() -> None:
    with pytest.raises(IllegalIntakeTransitionError, match=r"start_structuring.*ready_for_review"):
        transition(_READY_1, IntakeAction.START_STRUCTURING)


def test_captured_cannot_skip_to_ready_for_review() -> None:
    with pytest.raises(IllegalIntakeTransitionError):
        transition(_CAPTURED_1, IntakeAction.STRUCTURING_SUCCESS)


def test_captured_cannot_force_text() -> None:
    with pytest.raises(IllegalIntakeTransitionError):
        transition(_CAPTURED_1, IntakeAction.FORCE_TEXT)


def test_ready_for_review_cannot_re_record() -> None:
    with pytest.raises(IllegalIntakeTransitionError):
        transition(_READY_1, IntakeAction.RECORD_UNUSABLE)


def test_failed_is_terminal() -> None:
    for action in IntakeAction:
        with pytest.raises(IllegalIntakeTransitionError):
            transition(_FAILED_1, action)


# -- classify_transcript_usability heuristic --


def test_empty_transcript_is_unusable() -> None:
    assert classify_transcript_usability("") == "unusable"


def test_whitespace_only_transcript_is_unusable() -> None:
    assert classify_transcript_usability("   \n\t ") == "unusable"


def test_short_transcript_is_unusable() -> None:
    assert classify_transcript_usability("abc") == "unusable"


def test_boundary_at_partial_min_is_partial() -> None:
    assert classify_transcript_usability("a" * PARTIAL_MIN_CHARS) == "partial"


def test_just_below_usable_is_partial() -> None:
    assert classify_transcript_usability("a" * (USABLE_MIN_CHARS - 1)) == "partial"


def test_boundary_at_usable_min_is_usable() -> None:
    assert classify_transcript_usability("a" * USABLE_MIN_CHARS) == "usable"


def test_long_transcript_is_usable() -> None:
    assert classify_transcript_usability("the quick brown fox jumps over the lazy dog") == "usable"
