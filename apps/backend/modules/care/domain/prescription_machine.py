"""MOD-006: the pure prescription lifecycle state machine (PHASE-8 T03, #419).

The companion case machine lives in ``state_machine.py``.

Prescription lifecycle
----------------------

Enum values mirror ``care_prescriptions.status``
(``CANONICAL_RX_STATUSES`` in ``care.schema.models``). The combined
``ApprovedIssued`` state is approval-and-issuance in one act (CONTEXT.md
glossary, ``revision-freeze approval``): the doctor's saved working revision is
frozen, ``issued_at`` and ``attributed_doctor`` set, and the prescription
lands directly in ``issued`` - there is no dwell between approving and
issuing. The ``approved`` status value in the DB vocabulary is not a machine
state for that reason; only ``issued`` (the reached-after-approval status) is.

    [Draft] --SAVE_REVISION--> [DoctorReviewed] --APPROVE--> [ApprovedIssued]
        |                                                  |    --FULFILL--> [Fulfilled]
        +--APPROVE (gate)----------------------------------+
        +--REJECT (reason)----------> [Rejected] --CREATE_DRAFT (cap)--> [Draft]
    [DoctorReviewed] --REJECT (reason)--> [Rejected]

Invariants the machine enforces structurally:

- **Approval gate:** ``APPROVE`` requires ``verification_declaration=True``
  (CONTEXT.md glossary, ``verification declaration``) - a declaration-less
  approval is rejected, so no prescription is ever issued without the doctor's
  recorded, double-checked review (REQ-023 hard gate).
- **Rejection reason:** ``REJECT`` requires a non-empty reason; ``Rejected``
  is the branch where the drafting assistant tries again.
- **Drafting cap:** a new AI draft is only generated while the case has fewer
  than 2 rejected drafts (CONTEXT.md glossary, ``drafting cap``; max 2
  rejections), so at most the first two rejected attempts may be redrafted and
  the third AI draft is blocked. The cap limits only draft *generation* -
  manual authoring, edit-and-approve, and close-without-prescription stay open
  (those live at the facade, not here).
- ``Fulfilled`` is a terminal state reached only via inbound fulfillment events
  from PHASE-10; no action in this ticket triggers it, but the edge is legal.

Revision-freeze (issued ``rx_items`` must match the saved revision, never the
raw ``draft_snapshot``) and ``edited_yn`` derivation are data invariants
enforced at the facade layer, not machine transitions.

Pure decision logic only: no schema, facade or adapter imports - the
persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.care.domain.exceptions import (
    CareRxDraftCapReachedError,
    IllegalPrescriptionTransitionError,
)


class PrescriptionStatus(StrEnum):
    """Prescription lifecycle status (mirrors ``care_prescriptions.status``).

    ``APPROVED_ISSUED`` is approval-and-issuance in one act (revision-freeze
    approval): the value is ``issued`` because the machine lands directly in
    the issued status; the DB vocabulary's ``approved`` value is not a dwell
    state here.
    """

    DRAFT = "draft"
    DOCTOR_REVIEWED = "doctor_reviewed"
    APPROVED_ISSUED = "issued"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"


class PrescriptionAction(StrEnum):
    """Lifecycle actions a prescription can be asked to take."""

    # A fresh AI draft; Draft -> Draft (regenerate) or Rejected -> Draft
    # (redraft after rejection). Gated on the drafting cap.
    CREATE_DRAFT = "create_draft"
    # Doctor saves the working revision; Draft -> Doctor Reviewed and onwards
    # (self-loop) - the approved revision is this state, never the raw draft.
    SAVE_REVISION = "save_revision"
    # Revision-freeze approval; Draft/Doctor Reviewed -> Approved & Issued.
    # Requires verification_declaration=true.
    APPROVE = "approve"
    # Doctor rejection; Draft/Doctor Reviewed -> Rejected. Requires a reason.
    REJECT = "reject"
    # Inbound fulfillment from PHASE-10; Approved & Issued -> Fulfilled (stub).
    FULFILL = "fulfill"


#: The drafting cap: a new AI draft is only generated while the case has fewer
#: than 2 rejected drafts (at most the first 2 rejected attempts may be
#: redrafted; the 3rd AI draft is blocked). Mirrors CONTEXT.md ``drafting cap``
#: and the intake module's max-3 re-submission pattern.
MAX_REJECTED_DRAFTS: int = 2


def can_create_draft(rejected_count: int) -> bool:
    """Return True while the drafting cap still admits a new AI draft.

    A new AI draft is only allowed while the care case has fewer than 2
    rejected drafts - so the 3rd AI draft is blocked and manual authoring stays
    the always-open fallback (CONTEXT.md glossary, ``drafting cap``).
    """
    return rejected_count < MAX_REJECTED_DRAFTS


@dataclass(frozen=True)
class PrescriptionState:
    """One immutable snapshot of a prescription's lifecycle.

    ``rejected_count`` counts the rejected drafts recorded for this case so far
    (incremented by each ``REJECT``); the drafting cap reads it to decide
    whether ``CREATE_DRAFT`` may still generate a fresh AI draft.
    """

    status: PrescriptionStatus
    rejected_count: int = 0


#: Initial state for a freshly created prescription (attempt 1, no rejections).
DRAFT: PrescriptionState = PrescriptionState(status=PrescriptionStatus.DRAFT, rejected_count=0)

#: ``(status, action) ->`` the target status for a fixed (non-conditional) edge.
#: ``CREATE_DRAFT`` and ``REJECT`` carry extra state (cap / reason) handled in
#: ``transition``; ``APPROVE`` is conditional on the verification declaration.
_LEGAL_TRANSITIONS: dict[tuple[PrescriptionStatus, PrescriptionAction], PrescriptionStatus] = {
    # Regenerate the working draft in place; Draft -> Draft (cap-gated).
    (PrescriptionStatus.DRAFT, PrescriptionAction.CREATE_DRAFT): PrescriptionStatus.DRAFT,
    # Doctor saves the working revision; Draft -> Doctor Reviewed.
    (PrescriptionStatus.DRAFT, PrescriptionAction.SAVE_REVISION): (
        PrescriptionStatus.DOCTOR_REVIEWED
    ),
    # Doctor saves a further revision; Doctor Reviewed -> Doctor Reviewed.
    (PrescriptionStatus.DOCTOR_REVIEWED, PrescriptionAction.SAVE_REVISION): (
        PrescriptionStatus.DOCTOR_REVIEWED
    ),
    # Redraft after rejection; Rejected -> Draft (cap-gated).
    (PrescriptionStatus.REJECTED, PrescriptionAction.CREATE_DRAFT): PrescriptionStatus.DRAFT,
    # Inbound fulfillment from PHASE-10; Approved & Issued -> Fulfilled (stub).
    (PrescriptionStatus.APPROVED_ISSUED, PrescriptionAction.FULFILL): PrescriptionStatus.FULFILLED,
}


def transition(
    state: PrescriptionState,
    action: PrescriptionAction,
    *,
    verification_declaration: bool = False,
    rejection_reason: str | None = None,
) -> PrescriptionState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    ``CREATE_DRAFT`` enforces the drafting cap: it raises unless
    ``can_create_draft(state.rejected_count)``, so a 3rd AI draft is blocked
    once 2 drafts have been rejected (exactly the AC "drafting cap blocks 3rd
    AI draft but allows manual authoring at any time" - manual authoring is a
    facade path, not a machine action). ``APPROVE`` enforces the verification
    declaration: it raises unless ``verification_declaration`` is True.
    ``REJECT`` enforces the rejection reason: it raises when
    ``rejection_reason`` is empty and answers a ``Rejected`` state carrying one
    more ``rejected_count``.

    ``FULFILL`` moves ``ApprovedIssued`` -> ``Fulfilled`` only; ``Fulfilled``
    is terminal. ``ApprovedIssued`` is terminal for every action except
    ``FULFILL``.

    Raises :class:`IllegalPrescriptionTransitionError` for every edge outside
    the binding transition table and for missing transition prerequisites.
    """
    if action is PrescriptionAction.CREATE_DRAFT:
        if state.status not in (PrescriptionStatus.DRAFT, PrescriptionStatus.REJECTED):
            raise IllegalPrescriptionTransitionError(
                f"{action.value} is illegal while the prescription is {state.status.value}"
            )
        if not can_create_draft(state.rejected_count):
            raise CareRxDraftCapReachedError(
                f"{action.value} is illegal: drafting cap reached "
                f"({state.rejected_count} rejected drafts; max {MAX_REJECTED_DRAFTS})"
            )
        return PrescriptionState(
            status=PrescriptionStatus.DRAFT, rejected_count=state.rejected_count
        )

    if action in (PrescriptionAction.APPROVE, PrescriptionAction.REJECT):
        if state.status not in (PrescriptionStatus.DRAFT, PrescriptionStatus.DOCTOR_REVIEWED):
            raise IllegalPrescriptionTransitionError(
                f"{action.value} is illegal while the prescription is {state.status.value}"
            )
        if action is PrescriptionAction.APPROVE:
            # Defense-in-depth: the facade's ``_check_approval_declaration``
            # (the one replaceable CFL-002 compliance seam, ADR-0014/0015) is
            # the primary gate; this machine guard blocks a declaration-less
            # approval independently.
            if not verification_declaration:
                raise IllegalPrescriptionTransitionError(
                    f"{action.value} requires verification_declaration=true"
                )
            return PrescriptionState(
                status=PrescriptionStatus.APPROVED_ISSUED, rejected_count=state.rejected_count
            )
        if not rejection_reason:
            raise IllegalPrescriptionTransitionError(f"{action.value} requires a rejection reason")
        return PrescriptionState(
            status=PrescriptionStatus.REJECTED, rejected_count=state.rejected_count + 1
        )

    target = _LEGAL_TRANSITIONS.get((state.status, action))
    if target is None:
        raise IllegalPrescriptionTransitionError(
            f"{action.value} is illegal while the prescription is {state.status.value}"
        )
    return PrescriptionState(status=target, rejected_count=state.rejected_count)
