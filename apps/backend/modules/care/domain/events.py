"""MOD-006: canonical care-case event payloads and builders (PHASE-8 T02, #418).

Event names follow the registry dot-notation in ``internal-modules.md`` §4.2
(``bus.events`` is the code-side source of truth); payloads are typed Pydantic
models (coding-standards §3) and carry only orchestration/audit facts - ids and
lifecycle facts - never PHI. The clinical content (pre-summary fields,
prescription items) lives in the ``care`` / ``intake`` schemas and is read by
the consuming facade; only identifiers travel on the bus (security-phii-
standards no-PHI). Every builder answers an :class:`~bus.envelope.Envelope` the
care facade writes into ``care.care_outbox`` in the SAME transaction as the
state change (ADR-0002 §1).

The prescription event payloads (draft_created, reviewed, approved, rejected,
issued) land alongside the case lifecycle events here (PHASE-8 T03, #419).
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
)

PRODUCER_MODULE = "care"

PrescriptionSource = Literal["ai_draft", "manual"]


class CaseConsultCompletePayload(BaseModel):
    """Subject of ``case.consult_complete``: the consult-complete milestone.

    Fired when the doctor closes the off-platform consult on-platform in one
    action (CONTEXT.md glossary, ``consult complete milestone``): the case
    moves PreSummary -> PrescriptionPending and the patient gets their single
    notification. Carries only ids and lifecycle facts - no clinical content.

    Deliberately NOT a regulated act: the pre-summary handshake and consult
    completion are operational lifecycle events, not issuance/rejection acts
    (events.py REGULATED_ACT_TYPES scope comment - case consult events are
    skipped from the hash chain).
    """

    case_id: int
    patient_id: int
    doctor_id: int
    pre_summary_id: int | None


class CaseClosedPayload(BaseModel):
    """Subject of ``case.closed``: the doctor closed the visit with no prescription.

    Fired when the doctor's deliberate close-without-prescription terminal
    action lands (CONTEXT.md glossary, ``close-without-prescription``); the
    case leaves the pending list. ``close_reason`` is a short, PHI-free
    record of why the visit closed. A rejected draft never triggers this
    event - only the explicit doctor close does.
    """

    case_id: int
    patient_id: int
    doctor_id: int
    close_reason: str


def case_consult_complete_envelope(
    *, case_id: int, patient_id: int, doctor_id: int, pre_summary_id: int | None
) -> Envelope[CaseConsultCompletePayload]:
    """Build the ``case.consult_complete`` envelope for the ``care`` outbox."""
    return Envelope[CaseConsultCompletePayload](
        event_id=uuid4(),
        event_type=EVENT_CASE_CONSULT_COMPLETE,
        producer=PRODUCER_MODULE,
        payload=CaseConsultCompletePayload(
            case_id=case_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            pre_summary_id=pre_summary_id,
        ),
    )


def case_closed_envelope(
    *, case_id: int, patient_id: int, doctor_id: int, close_reason: str
) -> Envelope[CaseClosedPayload]:
    """Build the ``case.closed`` envelope for the ``care`` outbox."""
    return Envelope[CaseClosedPayload](
        event_id=uuid4(),
        event_type=EVENT_CASE_CLOSED,
        producer=PRODUCER_MODULE,
        payload=CaseClosedPayload(
            case_id=case_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            close_reason=close_reason,
        ),
    )


class PrescriptionDraftCreatedPayload(BaseModel):
    """Subject of ``prescription.draft_created``: an AI or manual draft exists.

    Fired when ``create_rx_draft`` stores a draft (revision source
    ``ai_draft`` from the drafting assistant's immutable draft snapshot, or
    ``manual`` from the doctor's own ``rx_items`` - CONTEXT.md glossary,
    ``prescription source``). ``attempt_no`` names the draft attempt within the
    case so consumers can trace the drafting-cap budget. Carries only ids and
    lifecycle facts - never the draft content (no-PHI envelope).
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int
    source: PrescriptionSource
    attempt_no: int


class PrescriptionReviewedPayload(BaseModel):
    """Subject of ``prescription.reviewed``: the doctor saved a working revision.

    Fired when ``save_rx_revision`` records the doctor's working revision on
    the ``Draft``/``DoctorReviewed`` row (the state approval freezes). The
    revision content stays in the ``care`` schema; only the ids and lifecycle
    facts travel. Operational event - deliberately NOT a regulated act.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int


class PrescriptionApprovedPayload(BaseModel):
    """Subject of ``prescription.approved``: the doctor approved the revision.

    Fired on revision-freeze approval (CONTEXT.md glossary, ``revision-freeze
    approval``): the saved working revision is frozen, ``issued_at`` and
    ``attributed_doctor`` are set, and ``edited_yn`` is derived against the
    immutable draft snapshot (never carried on the bus - only the boolean
    travels). This is a regulated act and enters the MOD-011 hash chain.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int
    edited_yn: bool


class PrescriptionRejectedPayload(BaseModel):
    """Subject of ``prescription.rejected``: the doctor rejected a draft.

    Fired when ``reject_prescription`` records the rejection (reason required,
    enforced by the prescription state machine) on ``care_rx_approvals``.
    ``reason`` is a short, PHI-free descriptor of why the draft was rejected
    (e.g. "wrong_dosage"); it counts against the drafting cap. Deliberately
    does not auto-close the case. Regulated act; the non-empty reason is
    enforced by the machine transition gate, not this model.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int
    reason: str


class PrescriptionIssuedPayload(BaseModel):
    """Subject of ``prescription.issued``: the approved revision was issued.

    Fired together with ``prescription.approved`` when approval freezes the
    doctor's working revision into the issued e-prescription (CONTEXT.md
    glossary, ``e-prescription``): the issued artifact is immutable and
    attributed to the doctor, with no supersede or void path. Regulated act.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int


def prescription_draft_created_envelope(
    *,
    case_id: int,
    prescription_id: int,
    patient_id: int,
    doctor_id: int,
    source: str,
    attempt_no: int,
) -> Envelope[PrescriptionDraftCreatedPayload]:
    """Build the ``prescription.draft_created`` envelope for the ``care`` outbox."""
    return Envelope[PrescriptionDraftCreatedPayload](
        event_id=uuid4(),
        event_type=EVENT_PRESCRIPTION_DRAFT_CREATED,
        producer=PRODUCER_MODULE,
        payload=PrescriptionDraftCreatedPayload(
            case_id=case_id,
            prescription_id=prescription_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            source=source,
            attempt_no=attempt_no,
        ),
    )


def prescription_reviewed_envelope(
    *, case_id: int, prescription_id: int, patient_id: int, doctor_id: int
) -> Envelope[PrescriptionReviewedPayload]:
    """Build the ``prescription.reviewed`` envelope for the ``care`` outbox."""
    return Envelope[PrescriptionReviewedPayload](
        event_id=uuid4(),
        event_type=EVENT_PRESCRIPTION_REVIEWED,
        producer=PRODUCER_MODULE,
        payload=PrescriptionReviewedPayload(
            case_id=case_id,
            prescription_id=prescription_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
        ),
    )


def prescription_approved_envelope(
    *,
    case_id: int,
    prescription_id: int,
    patient_id: int,
    doctor_id: int,
    edited_yn: bool,
) -> Envelope[PrescriptionApprovedPayload]:
    """Build the ``prescription.approved`` envelope for the ``care`` outbox."""
    return Envelope[PrescriptionApprovedPayload](
        event_id=uuid4(),
        event_type=EVENT_PRESCRIPTION_APPROVED,
        producer=PRODUCER_MODULE,
        payload=PrescriptionApprovedPayload(
            case_id=case_id,
            prescription_id=prescription_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            edited_yn=edited_yn,
        ),
    )


def prescription_rejected_envelope(
    *,
    case_id: int,
    prescription_id: int,
    patient_id: int,
    doctor_id: int,
    reason: str,
) -> Envelope[PrescriptionRejectedPayload]:
    """Build the ``prescription.rejected`` envelope for the ``care`` outbox."""
    return Envelope[PrescriptionRejectedPayload](
        event_id=uuid4(),
        event_type=EVENT_PRESCRIPTION_REJECTED,
        producer=PRODUCER_MODULE,
        payload=PrescriptionRejectedPayload(
            case_id=case_id,
            prescription_id=prescription_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            reason=reason,
        ),
    )


def prescription_issued_envelope(
    *, case_id: int, prescription_id: int, patient_id: int, doctor_id: int
) -> Envelope[PrescriptionIssuedPayload]:
    """Build the ``prescription.issued`` envelope for the ``care`` outbox."""
    return Envelope[PrescriptionIssuedPayload](
        event_id=uuid4(),
        event_type=EVENT_PRESCRIPTION_ISSUED,
        producer=PRODUCER_MODULE,
        payload=PrescriptionIssuedPayload(
            case_id=case_id,
            prescription_id=prescription_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
        ),
    )
