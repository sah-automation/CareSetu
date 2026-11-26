"""PHASE-8 T02: care-case lifecycle state-machine transition legality (#418, #426, FEAT-008).

Three dwell stages (CONTEXT.md glossary: ``case stage``): PreSummary ->
PrescriptionPending -> Closed.  ``ConsultComplete`` is the audited milestone
on the PreSummary -> PrescriptionPending transition (gated on a finalized
pre-summary), never a dwell state; ``CLOSE_WITHOUT_RX`` is the doctor's
deliberate terminal close-from-PrescriptionPending, requires a close reason,
and is never legal mid-handshake (review-close T3, #429).  The machine is pure
(no I/O, no schema imports), so the unit suite pins the full status x action
matrix without a database -- every illegal edge raises the typed
:class:`IllegalCareTransitionError`.
"""

from __future__ import annotations

import pytest

from modules.care.domain.exceptions import IllegalCareTransitionError
from modules.care.domain.state_machine import (
    PRE_SUMMARY,
    CaseAction,
    CaseStage,
    CaseState,
    transition,
)

_PRE_SUMMARY = CaseState(stage=CaseStage.PRE_SUMMARY)
_PRESCRIPTION_PENDING = CaseState(stage=CaseStage.PRESCRIPTION_PENDING)
_CLOSED = CaseState(stage=CaseStage.CLOSED)


def test_initial_state_is_pre_summary() -> None:
    assert PRE_SUMMARY.stage is CaseStage.PRE_SUMMARY
    assert PRE_SUMMARY.close_reason is None
    assert _PRE_SUMMARY == PRE_SUMMARY


def test_consult_complete_moves_to_prescription_pending() -> None:
    next_state = transition(
        _PRE_SUMMARY, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
    )

    assert next_state.stage is CaseStage.PRESCRIPTION_PENDING
    assert next_state.close_reason is None


def test_consult_complete_gate_rejects_when_pre_summary_not_finalized() -> None:
    with pytest.raises(IllegalCareTransitionError, match="requires a finalized pre-summary"):
        transition(_PRE_SUMMARY, CaseAction.MARK_CONSULT_COMPLETE)


def test_consult_complete_gate_rejects_when_pre_summary_finalized_false() -> None:
    with pytest.raises(IllegalCareTransitionError, match="requires a finalized pre-summary"):
        transition(_PRE_SUMMARY, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=False)


def test_consult_complete_is_illegal_from_prescription_pending() -> None:
    with pytest.raises(IllegalCareTransitionError):
        transition(
            _PRESCRIPTION_PENDING, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
        )


def test_consult_complete_is_illegal_from_closed() -> None:
    with pytest.raises(IllegalCareTransitionError):
        transition(_CLOSED, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True)


def test_close_without_rx_is_illegal_from_pre_summary() -> None:
    with pytest.raises(IllegalCareTransitionError, match="pre_summary"):
        transition(_PRE_SUMMARY, CaseAction.CLOSE_WITHOUT_RX, close_reason="doctor_rejected")


def test_close_without_rx_from_prescription_pending_is_terminal() -> None:
    next_state = transition(
        _PRESCRIPTION_PENDING, CaseAction.CLOSE_WITHOUT_RX, close_reason="no_show"
    )

    assert next_state.stage is CaseStage.CLOSED
    assert next_state.close_reason == "no_show"


def test_close_without_rx_requires_reason() -> None:
    with pytest.raises(IllegalCareTransitionError, match="requires a close reason"):
        transition(_PRESCRIPTION_PENDING, CaseAction.CLOSE_WITHOUT_RX)


def test_close_without_rx_rejects_empty_reason() -> None:
    with pytest.raises(IllegalCareTransitionError, match="requires a close reason"):
        transition(_PRESCRIPTION_PENDING, CaseAction.CLOSE_WITHOUT_RX, close_reason="")


def test_close_without_rx_is_illegal_from_closed() -> None:
    with pytest.raises(IllegalCareTransitionError):
        transition(_CLOSED, CaseAction.CLOSE_WITHOUT_RX, close_reason="duplicate")


def test_closed_is_terminal_for_all_actions() -> None:
    for action in CaseAction:
        with pytest.raises(IllegalCareTransitionError):
            transition(_CLOSED, action)


def test_transition_returns_new_immutable_state() -> None:
    snapshot = CaseState(stage=CaseStage.PRE_SUMMARY)
    transition(snapshot, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True)
    assert snapshot == CaseState(stage=CaseStage.PRE_SUMMARY)


def test_consult_complete_does_not_carry_close_reason() -> None:
    state = CaseState(stage=CaseStage.PRE_SUMMARY, close_reason="patient_withdrawn")
    next_state = transition(state, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True)
    assert next_state.close_reason is None


def test_illegal_message_names_the_action_and_stage() -> None:
    with pytest.raises(
        IllegalCareTransitionError, match=r"mark_consult_complete.*prescription_pending"
    ):
        transition(
            _PRESCRIPTION_PENDING, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
        )


# ---------------------------------------------------------------------------
# Exhaustive parametrised matrix
# ---------------------------------------------------------------------------

# Legal edges: (stage, action, kwargs) -> expected next state
# CONTEXT.md glossary: ConsultComplete is the milestone on PreSummary ->
# PrescriptionPending, never a dwell state. Close is legal from
# PrescriptionPending only (#429): a case is never closed mid-handshake.
# Closed is terminal.
_LEGAL_EDGES: dict[tuple[CaseStage, CaseAction], tuple[CaseStage, dict[str, object]]] = {
    (CaseStage.PRE_SUMMARY, CaseAction.MARK_CONSULT_COMPLETE): (
        CaseStage.PRESCRIPTION_PENDING,
        {"pre_summary_finalized": True},
    ),
    (CaseStage.PRESCRIPTION_PENDING, CaseAction.CLOSE_WITHOUT_RX): (
        CaseStage.CLOSED,
        {"close_reason": "no_show"},
    ),
}

_ALL_STAGES = (
    CaseStage.PRE_SUMMARY,
    CaseStage.PRESCRIPTION_PENDING,
    CaseStage.CLOSED,
)
_ALL_ACTIONS = (
    CaseAction.MARK_CONSULT_COMPLETE,
    CaseAction.CLOSE_WITHOUT_RX,
)


@pytest.mark.parametrize("stage", _ALL_STAGES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_stage_action_pair_matches_the_binding_machine(
    stage: CaseStage, action: CaseAction
) -> None:
    state = CaseState(stage=stage)
    expected = _LEGAL_EDGES.get((stage, action))

    if expected is None:
        with pytest.raises(IllegalCareTransitionError):
            transition(state, action)
    else:
        expected_stage, kwargs = expected
        result = transition(state, action, **kwargs)
        assert result.stage is expected_stage


def test_consult_complete_gate_boundary_with_finalized_flag_only() -> None:
    """Pre-summary -> Prescription Pending with the explicit gate flag."""
    result = transition(
        CaseState(CaseStage.PRE_SUMMARY),
        CaseAction.MARK_CONSULT_COMPLETE,
        pre_summary_finalized=True,
    )
    assert result.stage is CaseStage.PRESCRIPTION_PENDING
    assert result.close_reason is None


def test_close_with_valid_reason_is_still_illegal_from_pre_summary() -> None:
    for reason in ("patient_withdrawn", "duplicate"):
        with pytest.raises(IllegalCareTransitionError, match="pre_summary"):
            transition(_PRE_SUMMARY, CaseAction.CLOSE_WITHOUT_RX, close_reason=reason)


def test_close_from_prescription_pending_with_system_reason() -> None:
    result = transition(_PRESCRIPTION_PENDING, CaseAction.CLOSE_WITHOUT_RX, close_reason="system")
    assert result.stage is CaseStage.CLOSED
    assert result.close_reason == "system"
