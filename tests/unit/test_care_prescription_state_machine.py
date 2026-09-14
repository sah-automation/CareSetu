"""PHASE-8 T03: prescription lifecycle state-machine transition legality (#419).

Five statuses (CONTEXT.md glossary: ``prescription machine``): Draft,
DoctorReviewed, ApprovedIssued (the DB value is ``issued`` - approval and
issuance are one act), Rejected (branch for the drafting-assistant retry),
Fulfilled (terminal inbound from PHASE-10).  The machine is pure (no I/O,
no schema imports), so the unit suite pins the full status x action matrix
without a database -- every illegal edge raises the typed
:class:`IllegalPrescriptionTransitionError`.

Key invariants exercised here:

- **Approval gate:** ``APPROVE`` requires ``verification_declaration=True``
  (``verification declaration`` glossary term) so no prescription is ever
  issued without the doctor's recorded, double-checked review (REQ-023).
- **Rejection reason:** ``REJECT`` requires a non-empty reason; rejected drafts
  count against the drafting cap.
- **Drafting cap:** ``CREATE_DRAFT`` is blocked once the rejection count
  reaches ``MAX_REJECTED_DRAFTS`` (2), so a 3rd AI draft is never generated
  (``drafting cap`` glossary term).
- ``Fulfilled`` is terminal; ``ApprovedIssued`` is terminal except for
  ``FULFILL`` (inbound from PHASE-10).
"""

from __future__ import annotations

import pytest

from modules.care.domain.exceptions import IllegalPrescriptionTransitionError
from modules.care.domain.prescription_machine import (
    DRAFT,
    MAX_REJECTED_DRAFTS,
    PrescriptionAction,
    PrescriptionState,
    PrescriptionStatus,
    can_create_draft,
    transition,
)

_DRAFT = PrescriptionState(status=PrescriptionStatus.DRAFT, rejected_count=0)
_DOCTOR_REVIEWED = PrescriptionState(status=PrescriptionStatus.DOCTOR_REVIEWED, rejected_count=0)
_APPROVED_ISSUED = PrescriptionState(status=PrescriptionStatus.APPROVED_ISSUED, rejected_count=0)
_REJECTED = PrescriptionState(status=PrescriptionStatus.REJECTED, rejected_count=1)
_FULFILLED = PrescriptionState(status=PrescriptionStatus.FULFILLED, rejected_count=0)


# ---------------------------------------------------------------------------
# can_create_draft gate
# ---------------------------------------------------------------------------


def test_can_create_draft_when_no_rejections() -> None:
    assert can_create_draft(0) is True


def test_can_create_draft_after_one_rejection() -> None:
    assert can_create_draft(1) is True


def test_can_create_draft_blocked_at_two_rejections() -> None:
    assert can_create_draft(2) is False


def test_can_create_draft_blocked_above() -> None:
    assert can_create_draft(3) is False


def test_max_rejected_drafts_constant() -> None:
    assert MAX_REJECTED_DRAFTS == 2


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_state_is_draft() -> None:
    assert DRAFT.status is PrescriptionStatus.DRAFT
    assert DRAFT.rejected_count == 0
    assert _DRAFT == DRAFT


# ---------------------------------------------------------------------------
# SAVE_REVISION: Draft -> DoctorReviewed, DoctorReviewed self-loop
# ---------------------------------------------------------------------------


def test_save_revision_moves_to_doctor_reviewed() -> None:
    next_state = transition(_DRAFT, PrescriptionAction.SAVE_REVISION)
    assert next_state.status is PrescriptionStatus.DOCTOR_REVIEWED
    assert next_state.rejected_count == 0


def test_save_revision_from_doctor_reviewed_self_loop() -> None:
    state = PrescriptionState(status=PrescriptionStatus.DOCTOR_REVIEWED, rejected_count=0)
    next_state = transition(state, PrescriptionAction.SAVE_REVISION)
    assert next_state.status is PrescriptionStatus.DOCTOR_REVIEWED
    assert next_state.rejected_count == 0


def test_save_revision_is_illegal_from_approved_issued() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_APPROVED_ISSUED, PrescriptionAction.SAVE_REVISION)


def test_save_revision_is_illegal_from_rejected() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_REJECTED, PrescriptionAction.SAVE_REVISION)


def test_save_revision_is_illegal_from_fulfilled() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_FULFILLED, PrescriptionAction.SAVE_REVISION)


# ---------------------------------------------------------------------------
# CREATE_DRAFT: regenerates from Draft, redrafts from Rejected (cap-gated)
# ---------------------------------------------------------------------------


def test_create_draft_regenerates_from_draft() -> None:
    next_state = transition(_DRAFT, PrescriptionAction.CREATE_DRAFT)
    assert next_state.status is PrescriptionStatus.DRAFT
    assert next_state.rejected_count == 0


def test_create_draft_from_rejected_moves_to_draft() -> None:
    next_state = transition(_REJECTED, PrescriptionAction.CREATE_DRAFT)
    assert next_state.status is PrescriptionStatus.DRAFT
    assert next_state.rejected_count == 1


def test_create_draft_blocked_after_two_rejections() -> None:
    state = PrescriptionState(status=PrescriptionStatus.REJECTED, rejected_count=2)
    with pytest.raises(IllegalPrescriptionTransitionError, match="drafting cap reached"):
        transition(state, PrescriptionAction.CREATE_DRAFT)


def test_create_draft_is_illegal_from_doctor_reviewed() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_DOCTOR_REVIEWED, PrescriptionAction.CREATE_DRAFT)


def test_create_draft_is_illegal_from_approved_issued() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_APPROVED_ISSUED, PrescriptionAction.CREATE_DRAFT)


def test_create_draft_is_illegal_from_fulfilled() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_FULFILLED, PrescriptionAction.CREATE_DRAFT)


# ---------------------------------------------------------------------------
# APPROVE: Draft/DoctorReviewed -> ApprovedIssued (verification declaration gate)
# ---------------------------------------------------------------------------


def test_approve_from_draft_with_declaration() -> None:
    next_state = transition(_DRAFT, PrescriptionAction.APPROVE, verification_declaration=True)
    assert next_state.status is PrescriptionStatus.APPROVED_ISSUED
    assert next_state.rejected_count == 0


def test_approve_from_doctor_reviewed_with_declaration() -> None:
    state = PrescriptionState(status=PrescriptionStatus.DOCTOR_REVIEWED, rejected_count=1)
    next_state = transition(state, PrescriptionAction.APPROVE, verification_declaration=True)
    assert next_state.status is PrescriptionStatus.APPROVED_ISSUED
    assert next_state.rejected_count == 1


def test_approve_requires_verification_declaration() -> None:
    with pytest.raises(
        IllegalPrescriptionTransitionError, match="requires verification_declaration"
    ):
        transition(_DRAFT, PrescriptionAction.APPROVE, verification_declaration=False)


def test_approve_requires_verification_declaration_even_from_doctor_reviewed() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_DOCTOR_REVIEWED, PrescriptionAction.APPROVE, verification_declaration=False)


def test_approve_is_illegal_from_approved_issued() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_APPROVED_ISSUED, PrescriptionAction.APPROVE, verification_declaration=True)


def test_approve_is_illegal_from_rejected() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_REJECTED, PrescriptionAction.APPROVE, verification_declaration=True)


def test_approve_is_illegal_from_fulfilled() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_FULFILLED, PrescriptionAction.APPROVE, verification_declaration=True)


# ---------------------------------------------------------------------------
# REJECT: Draft/DoctorReviewed -> Rejected (rejection reason gate)
# ---------------------------------------------------------------------------


def test_reject_from_draft_with_reason() -> None:
    next_state = transition(_DRAFT, PrescriptionAction.REJECT, rejection_reason="wrong_dosage")
    assert next_state.status is PrescriptionStatus.REJECTED
    assert next_state.rejected_count == 1


def test_reject_from_doctor_reviewed_with_reason() -> None:
    state = PrescriptionState(status=PrescriptionStatus.DOCTOR_REVIEWED, rejected_count=1)
    next_state = transition(state, PrescriptionAction.REJECT, rejection_reason="incomplete")
    assert next_state.status is PrescriptionStatus.REJECTED
    assert next_state.rejected_count == 2


def test_reject_requires_reason() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError, match="requires a rejection reason"):
        transition(_DRAFT, PrescriptionAction.REJECT)


def test_reject_requires_non_empty_reason() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError, match="requires a rejection reason"):
        transition(_DRAFT, PrescriptionAction.REJECT, rejection_reason="")


def test_reject_is_illegal_from_approved_issued() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_APPROVED_ISSUED, PrescriptionAction.REJECT, rejection_reason="bad")


def test_reject_is_illegal_from_fulfilled() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_FULFILLED, PrescriptionAction.REJECT, rejection_reason="bad")


# ---------------------------------------------------------------------------
# FULFILL: ApprovedIssued -> Fulfilled (terminal inbound)
# ---------------------------------------------------------------------------


def test_fulfill_moves_to_fulfilled() -> None:
    next_state = transition(_APPROVED_ISSUED, PrescriptionAction.FULFILL)
    assert next_state.status is PrescriptionStatus.FULFILLED
    assert next_state.rejected_count == 0


def test_fulfill_is_illegal_from_draft() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_DRAFT, PrescriptionAction.FULFILL)


def test_fulfill_is_illegal_from_doctor_reviewed() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_DOCTOR_REVIEWED, PrescriptionAction.FULFILL)


def test_fulfill_is_illegal_from_rejected() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_REJECTED, PrescriptionAction.FULFILL)


def test_fulfill_is_illegal_from_fulfilled() -> None:
    with pytest.raises(IllegalPrescriptionTransitionError):
        transition(_FULFILLED, PrescriptionAction.FULFILL)


# ---------------------------------------------------------------------------
# Terminal states
# ---------------------------------------------------------------------------


def test_fulfilled_is_terminal_for_all_actions() -> None:
    for action in PrescriptionAction:
        with pytest.raises(IllegalPrescriptionTransitionError):
            transition(_FULFILLED, action)


def test_approved_issued_is_terminal_except_fulfill() -> None:
    for action in PrescriptionAction:
        if action is PrescriptionAction.FULFILL:
            next_state = transition(_APPROVED_ISSUED, action)
            assert next_state.status is PrescriptionStatus.FULFILLED
        else:
            with pytest.raises(IllegalPrescriptionTransitionError):
                transition(_APPROVED_ISSUED, action)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_transition_returns_new_immutable_state() -> None:
    original = PrescriptionState(status=PrescriptionStatus.DRAFT, rejected_count=0)
    next_state = transition(original, PrescriptionAction.SAVE_REVISION)
    assert original.status is PrescriptionStatus.DRAFT
    assert next_state.status is PrescriptionStatus.DOCTOR_REVIEWED


def test_transition_does_not_mutate_rejected_count_on_save_revision() -> None:
    state = PrescriptionState(status=PrescriptionStatus.DOCTOR_REVIEWED, rejected_count=1)
    next_state = transition(state, PrescriptionAction.SAVE_REVISION)
    assert state.rejected_count == 1
    assert next_state.rejected_count == 1


def test_transition_does_not_mutate_rejected_count_on_approve() -> None:
    state = PrescriptionState(status=PrescriptionStatus.DRAFT, rejected_count=1)
    next_state = transition(state, PrescriptionAction.APPROVE, verification_declaration=True)
    assert state.rejected_count == 1
    assert next_state.rejected_count == 1


def test_transition_does_not_mutate_rejected_count_on_fulfill() -> None:
    next_state = transition(_APPROVED_ISSUED, PrescriptionAction.FULFILL)
    assert next_state.rejected_count == 0


# ---------------------------------------------------------------------------
# Drafting cap full cycle: 1st -> reject -> 2nd -> reject -> 3rd blocked
# ---------------------------------------------------------------------------


def test_drafting_cap_allows_first_and_second_draft() -> None:
    d1 = transition(_DRAFT, PrescriptionAction.CREATE_DRAFT)
    assert d1.status is PrescriptionStatus.DRAFT
    r1 = transition(d1, PrescriptionAction.REJECT, rejection_reason="bad_1")
    assert r1.status is PrescriptionStatus.REJECTED
    assert r1.rejected_count == 1

    d2 = transition(r1, PrescriptionAction.CREATE_DRAFT)
    assert d2.status is PrescriptionStatus.DRAFT
    r2 = transition(d2, PrescriptionAction.REJECT, rejection_reason="bad_2")
    assert r2.status is PrescriptionStatus.REJECTED
    assert r2.rejected_count == 2

    with pytest.raises(IllegalPrescriptionTransitionError, match="drafting cap reached"):
        transition(r2, PrescriptionAction.CREATE_DRAFT)


def test_drafting_cap_manual_authoring_not_in_machine() -> None:
    """Manual authoring is a facade path; the machine only governs AI drafts."""
    # The machine does not have a MANUAL_AUTHOR action - that path bypasses
    # the cap entirely (CONTEXT.md drafting cap: manual authoring always open).
    assert PrescriptionAction.CREATE_DRAFT.value == "create_draft"


# ---------------------------------------------------------------------------
# Error messages name the action and current status
# ---------------------------------------------------------------------------


def test_illegal_error_names_the_action_and_status() -> None:
    with pytest.raises(
        IllegalPrescriptionTransitionError,
        match=r"fulfill.*draft",
    ):
        transition(_DRAFT, PrescriptionAction.FULFILL)


def test_illegal_save_revision_from_fulfilled() -> None:
    with pytest.raises(
        IllegalPrescriptionTransitionError,
        match=r"save_revision.*fulfilled",
    ):
        transition(_FULFILLED, PrescriptionAction.SAVE_REVISION)


# ---------------------------------------------------------------------------
# Exhaustive parametrised matrix
# ---------------------------------------------------------------------------

# Legal edges: (status, action) -> (expected_status, kwargs)
_LEGAL_EDGES: dict[
    tuple[PrescriptionStatus, PrescriptionAction],
    tuple[PrescriptionStatus, dict[str, object]],
] = {
    # CREATE_DRAFT: Draft -> Draft (regenerate), Rejected -> Draft (redraft)
    (PrescriptionStatus.DRAFT, PrescriptionAction.CREATE_DRAFT): (
        PrescriptionStatus.DRAFT,
        {},
    ),
    (PrescriptionStatus.REJECTED, PrescriptionAction.CREATE_DRAFT): (
        PrescriptionStatus.DRAFT,
        {},
    ),
    # SAVE_REVISION: Draft -> DoctorReviewed; DoctorReviewed -> DoctorReviewed
    (PrescriptionStatus.DRAFT, PrescriptionAction.SAVE_REVISION): (
        PrescriptionStatus.DOCTOR_REVIEWED,
        {},
    ),
    (PrescriptionStatus.DOCTOR_REVIEWED, PrescriptionAction.SAVE_REVISION): (
        PrescriptionStatus.DOCTOR_REVIEWED,
        {},
    ),
    # APPROVE: Draft/DoctorReviewed -> ApprovedIssued (requires declaration)
    (PrescriptionStatus.DRAFT, PrescriptionAction.APPROVE): (
        PrescriptionStatus.APPROVED_ISSUED,
        {"verification_declaration": True},
    ),
    (PrescriptionStatus.DOCTOR_REVIEWED, PrescriptionAction.APPROVE): (
        PrescriptionStatus.APPROVED_ISSUED,
        {"verification_declaration": True},
    ),
    # REJECT: Draft/DoctorReviewed -> Rejected (requires reason, rc+1)
    (PrescriptionStatus.DRAFT, PrescriptionAction.REJECT): (
        PrescriptionStatus.REJECTED,
        {"rejection_reason": "wrong_dosage"},
    ),
    (PrescriptionStatus.DOCTOR_REVIEWED, PrescriptionAction.REJECT): (
        PrescriptionStatus.REJECTED,
        {"rejection_reason": "incomplete"},
    ),
    # FULFILL: ApprovedIssued -> Fulfilled
    (PrescriptionStatus.APPROVED_ISSUED, PrescriptionAction.FULFILL): (
        PrescriptionStatus.FULFILLED,
        {},
    ),
}

_ALL_STATUSES = (
    PrescriptionStatus.DRAFT,
    PrescriptionStatus.DOCTOR_REVIEWED,
    PrescriptionStatus.APPROVED_ISSUED,
    PrescriptionStatus.REJECTED,
    PrescriptionStatus.FULFILLED,
)
_ALL_ACTIONS = (
    PrescriptionAction.CREATE_DRAFT,
    PrescriptionAction.SAVE_REVISION,
    PrescriptionAction.APPROVE,
    PrescriptionAction.REJECT,
    PrescriptionAction.FULFILL,
)


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_matches_the_binding_machine(
    status: PrescriptionStatus, action: PrescriptionAction
) -> None:
    """Every (status, action) pair either matches the legal table or raises."""
    state = PrescriptionState(status=status, rejected_count=0)
    expected = _LEGAL_EDGES.get((status, action))

    if expected is None:
        with pytest.raises(IllegalPrescriptionTransitionError):
            transition(state, action)
    else:
        expected_status, kwargs = expected
        result = transition(state, action, **kwargs)
        assert result.status is expected_status


@pytest.mark.parametrize("status", _ALL_STATUSES)
@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_status_action_pair_respects_rejected_count(
    status: PrescriptionStatus, action: PrescriptionAction
) -> None:
    """Rejected count is preserved on non-reject transitions, incremented on reject."""
    state = PrescriptionState(status=status, rejected_count=1)
    expected = _LEGAL_EDGES.get((status, action))

    if expected is None:
        with pytest.raises(IllegalPrescriptionTransitionError):
            transition(state, action)
    else:
        _, kwargs = expected
        result = transition(state, action, **kwargs)
        if action is PrescriptionAction.REJECT:
            # REJECT always increments rejected_count by 1
            assert result.rejected_count == 2
        else:
            assert result.rejected_count == 1


# ---------------------------------------------------------------------------
# PrescriptionStatus enum sanity
# ---------------------------------------------------------------------------


def test_approved_issued_value_is_issued() -> None:
    """Maps to care_prescriptions.status value 'issued' (revision-freeze)."""
    assert PrescriptionStatus.APPROVED_ISSUED.value == "issued"


def test_enum_values_mirror_canonical_rx_statuses() -> None:
    from modules.care.schema.models import CANONICAL_RX_STATUSES

    machine_values = {s.value for s in PrescriptionStatus}
    # All machine statuses must be valid DB statuses
    assert machine_values.issubset(CANONICAL_RX_STATUSES)


# ---------------------------------------------------------------------------
# IllegalPrescriptionTransitionError derives from CareError
# ---------------------------------------------------------------------------


def test_error_inherits_care_error() -> None:
    from modules.care.domain.exceptions import CareError

    assert issubclass(IllegalPrescriptionTransitionError, CareError)


# ---------------------------------------------------------------------------
# Prescription event payload models (no-PHI envelope)
# ---------------------------------------------------------------------------


from bus.envelope import Envelope  # noqa: E402
from bus.events import (  # noqa: E402
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
)
from modules.care.domain.events import (  # noqa: E402
    PrescriptionApprovedPayload,
    PrescriptionDraftCreatedPayload,
    PrescriptionIssuedPayload,
    PrescriptionRejectedPayload,
    PrescriptionReviewedPayload,
    prescription_approved_envelope,
    prescription_draft_created_envelope,
    prescription_issued_envelope,
    prescription_rejected_envelope,
    prescription_reviewed_envelope,
)


def test_prescription_event_payloads_are_pydantic_models() -> None:
    from pydantic import BaseModel

    for model in (
        PrescriptionDraftCreatedPayload,
        PrescriptionReviewedPayload,
        PrescriptionApprovedPayload,
        PrescriptionRejectedPayload,
        PrescriptionIssuedPayload,
    ):
        assert issubclass(model, BaseModel)


def test_prescription_event_envelopes_build_typed_payloads() -> None:
    draft = prescription_draft_created_envelope(
        case_id=1, prescription_id=10, patient_id=100, doctor_id=42, source="ai_draft", attempt_no=1
    )
    assert isinstance(draft, Envelope)
    assert isinstance(draft.payload, PrescriptionDraftCreatedPayload)
    assert draft.event_type == EVENT_PRESCRIPTION_DRAFT_CREATED
    assert draft.producer == "care"
    assert draft.payload.source == "ai_draft"
    assert draft.payload.attempt_no == 1

    reviewed = prescription_reviewed_envelope(
        case_id=1, prescription_id=10, patient_id=100, doctor_id=42
    )
    assert isinstance(reviewed.payload, PrescriptionReviewedPayload)
    assert reviewed.event_type == EVENT_PRESCRIPTION_REVIEWED
    assert reviewed.payload.case_id == 1

    approved = prescription_approved_envelope(
        case_id=1, prescription_id=10, patient_id=100, doctor_id=42, edited_yn=True
    )
    assert isinstance(approved.payload, PrescriptionApprovedPayload)
    assert approved.event_type == EVENT_PRESCRIPTION_APPROVED
    assert approved.payload.edited_yn is True

    rejected = prescription_rejected_envelope(
        case_id=1, prescription_id=10, patient_id=100, doctor_id=42, reason="wrong_dosage"
    )
    assert isinstance(rejected.payload, PrescriptionRejectedPayload)
    assert rejected.event_type == EVENT_PRESCRIPTION_REJECTED
    assert rejected.payload.reason == "wrong_dosage"

    issued = prescription_issued_envelope(
        case_id=1,
        prescription_id=10,
        patient_id=100,
        doctor_id=42,
        occurred_at="2026-09-15T10:00:00+00:00",
    )
    assert isinstance(issued.payload, PrescriptionIssuedPayload)
    assert issued.event_type == EVENT_PRESCRIPTION_ISSUED
    assert issued.payload.prescription_id == 10


def test_prescription_draft_created_source_is_closed_vocabulary() -> None:
    from pydantic import ValidationError

    PrescriptionDraftCreatedPayload(
        case_id=1, prescription_id=10, patient_id=100, doctor_id=42, source="manual", attempt_no=2
    )
    with pytest.raises(ValidationError):
        PrescriptionDraftCreatedPayload(
            case_id=1,
            prescription_id=10,
            patient_id=100,
            doctor_id=42,
            source="typed_by_hand",
            attempt_no=1,
        )
