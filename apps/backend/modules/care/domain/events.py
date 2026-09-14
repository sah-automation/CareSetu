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
issued) belong to the prescription domain ticket (PHASE-8 T03, #419); this
module carries only the case lifecycle events.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import EVENT_CASE_CLOSED, EVENT_CASE_CONSULT_COMPLETE

PRODUCER_MODULE = "care"


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
