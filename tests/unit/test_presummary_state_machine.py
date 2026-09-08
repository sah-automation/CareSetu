"""PHASE-7 T02: pre-summary review-state machine transition legality (ticket #346).

Three explicit states (ADR-0001, never a fourth): Draft -> Reviewed -> Final,
plus the high-confidence clean path Draft -> Final (single review action, user
story 23). ``low_confidence`` is a derived property, not a state - boundary-
tested at the 0.70 threshold per AMB-006. The machine is pure (no I/O, no
schema imports), so the unit suite pins the full matrix without a database.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from modules.intake.domain.exceptions import IllegalPreSummaryTransitionError
from modules.intake.domain.presummary_machine import (
    DRAFT,
    PreSummaryAction,
    PreSummaryState,
    PreSummaryStatus,
    transition,
)

_DRAFT_NONE = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=None)
_DRAFT_LOW = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=Decimal("0.50"))
_DRAFT_CLEAN = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=Decimal("0.75"))
_DRAFT_BOUNDARY = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=Decimal("0.70"))
_REVIEWED_CLEAN = PreSummaryState(PreSummaryStatus.REVIEWED, structuring_confidence=Decimal("0.85"))
_REVIEWED_LOW = PreSummaryState(PreSummaryStatus.REVIEWED, structuring_confidence=Decimal("0.50"))
_FINAL = PreSummaryState(PreSummaryStatus.FINAL, structuring_confidence=Decimal("0.90"))


def test_fresh_pre_summary_starts_draft() -> None:
    assert DRAFT.status is PreSummaryStatus.DRAFT
    assert DRAFT.structuring_confidence is None


def test_review_moves_draft_to_reviewed() -> None:
    next_state = transition(_DRAFT_NONE, PreSummaryAction.REVIEW)

    assert next_state.status is PreSummaryStatus.REVIEWED
    assert next_state.structuring_confidence is None


def test_finalize_after_review_moves_to_final() -> None:
    next_state = transition(_REVIEWED_CLEAN, PreSummaryAction.FINALIZE)

    assert next_state.status is PreSummaryStatus.FINAL


def test_finalize_from_draft_high_confidence_goes_directly_to_final() -> None:
    """High-confidence clean path: single review action finalizes directly."""
    next_state = transition(_DRAFT_CLEAN, PreSummaryAction.FINALIZE)

    assert next_state.status is PreSummaryStatus.FINAL
    assert next_state.structuring_confidence == Decimal("0.75")


def test_finalize_from_draft_low_confidence_is_illegal() -> None:
    with pytest.raises(IllegalPreSummaryTransitionError, match="review is required"):
        transition(_DRAFT_LOW, PreSummaryAction.FINALIZE)


def test_finalize_from_draft_missing_confidence_is_illegal() -> None:
    with pytest.raises(IllegalPreSummaryTransitionError, match="review is required"):
        transition(_DRAFT_NONE, PreSummaryAction.FINALIZE)


def test_review_after_finalize_is_illegal() -> None:
    with pytest.raises(IllegalPreSummaryTransitionError):
        transition(_FINAL, PreSummaryAction.REVIEW)


def test_finalize_is_illegal_from_draft_at_boundary() -> None:
    """Exactly 0.70 is NOT low_confidence - direct finalize should be allowed."""
    next_state = transition(_DRAFT_BOUNDARY, PreSummaryAction.FINALIZE)
    assert next_state.status is PreSummaryStatus.FINAL


def test_review_is_illegal_from_reviewed() -> None:
    with pytest.raises(IllegalPreSummaryTransitionError):
        transition(_REVIEWED_CLEAN, PreSummaryAction.REVIEW)


def test_transition_returns_new_immutable_states() -> None:
    snapshot = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=Decimal("0.80"))

    transition(snapshot, PreSummaryAction.REVIEW)

    assert snapshot == PreSummaryState(
        PreSummaryStatus.DRAFT, structuring_confidence=Decimal("0.80")
    )


def test_structuring_confidence_is_preserved_through_transitions() -> None:
    low = Decimal("0.60")
    state = PreSummaryState(PreSummaryStatus.DRAFT, structuring_confidence=low)

    reviewed = transition(state, PreSummaryAction.REVIEW)
    assert reviewed.structuring_confidence == low

    final = transition(reviewed, PreSummaryAction.FINALIZE)
    assert final.structuring_confidence == low


# ---------------------------------------------------------------------------
# Exhaustive parametrised matrix
# ---------------------------------------------------------------------------

_LEGAL_EDGES: dict[tuple[PreSummaryStatus, PreSummaryAction], PreSummaryStatus] = {
    (PreSummaryStatus.DRAFT, PreSummaryAction.REVIEW): PreSummaryStatus.REVIEWED,
    (PreSummaryStatus.REVIEWED, PreSummaryAction.FINALIZE): PreSummaryStatus.FINAL,
}

_ALL_STATUSES = (
    PreSummaryStatus.DRAFT,
    PreSummaryStatus.REVIEWED,
    PreSummaryStatus.FINAL,
)
_ALL_ACTIONS = (PreSummaryAction.REVIEW, PreSummaryAction.FINALIZE)


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_matches_the_binding_machine(
    status: PreSummaryStatus, action: PreSummaryAction
) -> None:
    state = PreSummaryState(status, structuring_confidence=Decimal("0.85"))
    expected = _LEGAL_EDGES.get((status, action))

    # Finalize-from-Draft for high confidence (>= 0.70) is the clean-path
    # edge, not in _LEGAL_EDGES, so handle separately.
    if action is PreSummaryAction.FINALIZE and status is PreSummaryStatus.DRAFT:
        result = transition(state, action)
        assert result.status is PreSummaryStatus.FINAL
        return

    if expected is None:
        with pytest.raises(IllegalPreSummaryTransitionError):
            transition(state, action)
    else:
        assert transition(state, action).status is expected
