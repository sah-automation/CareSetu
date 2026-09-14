"""MOD-006: composition root for the ``care`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30): the
worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. PHASE-8 T08 (#424) freezes the module's event set: care
owns the producer payload models for every case / prescription event it
publishes so a claimed ``care_outbox`` row is reconstructed with a typed
payload before fan-out, and registers the module's §4.2 inbound
subscriptions - ``pre_summary.ready``, ``pre_summary.low_confidence`` and
``report.filed`` - as ledgered telemetry seams (#424).

The subscription bodies are deliberately connector-only: a finalized /
low-confidence pre-summary reaching the care module is a funnel fact, not a
write. The case-birth write (``pre_summary.ready`` -> ``care_cases`` row) and
the forced-review flag belong to later integration passes once the producer
event carries the patient identity (the payload today carries only
``intake_id`` + ``pre_summary_id``, and ``care_cases.patient_id`` is NOT
NULL); ``report.filed`` case-context attachment is Phase 9. Each handler
ledgers first (``run_handler``) so a replayed ``event_id`` is a no-op, then
logs a structured, PHI-free line and bumps its process-local counter -
mirroring the ``intake.started`` funnel telemetry seam (PHASE-7 T05 #369).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
    EVENT_REPORT_FILED,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.care.care_models import CARE_SCHEMA
from modules.care.domain.events import (
    CaseClosedPayload,
    CaseConsultCompletePayload,
    PrescriptionApprovedPayload,
    PrescriptionDraftCreatedPayload,
    PrescriptionRejectedPayload,
    PrescriptionReviewedPayload,
)

logger = logging.getLogger(__name__)


#: Consumer-side mirrors of the events care subscribes to. care cannot import
#: the producing module's ``domain`` package (ADR-0003 facade-only isolation),
#: so it validates each inbound payload against its own minimal, PHI-free copy.
#: Only the ids care needs are declared; producer-only fields (e.g. the report
#: filename) are ignored on validation - they never cross into care.
class CarePreSummaryReadyPayload(BaseModel):
    """Subject of ``pre_summary.ready``: a pre-summary draft reached the care module."""

    intake_id: int
    pre_summary_id: int


class CarePreSummaryLowConfidencePayload(BaseModel):
    """Subject of ``pre_summary.low_confidence``: a below-confidence pre-summary."""

    intake_id: int
    pre_summary_id: int


class CareReportFiledPayload(BaseModel):
    """Subject of ``report.filed``: a lab report was filed into the patient record."""

    order_id: int


#: Process-local running totals of delivered inbound telemetry events (KPI-001
#: "pipeline counters per loop stage" family). Zero at process start and bumped
#: once per ledger-deduped delivery, so a replayed ``event_id`` is idempotently
#: skipped and each count tracks distinct deliveries. Telemetry only - no
#: domain table and no outbox row is written by these seams (PHASE-8 T08 #424).
_pre_summary_ready_count: int = 0
_pre_summary_low_confidence_count: int = 0
_report_filed_count: int = 0


def pre_summary_ready_count() -> int:
    """Return the process-local count of distinct ``pre_summary.ready`` deliveries."""
    return _pre_summary_ready_count


def pre_summary_low_confidence_count() -> int:
    """Return the process-local count of distinct ``pre_summary.low_confidence`` deliveries."""
    return _pre_summary_low_confidence_count


def report_filed_count() -> int:
    """Return the process-local count of distinct ``report.filed`` deliveries."""
    return _report_filed_count


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the care module's event payload models + inbound subscriptions.

    MOD-006 owns the producer payload models for its own published events; the
    dispatcher reconstructs a claimed ``care_outbox`` row with each before
    fan-out. ``prescription.issued`` is deliberately absent - its registry model
    is owned by MOD-003 (health), whose ``register_payload_model`` runs before
    care's in the composition order, so re-registering it would trip the
    duplicate guard. The three §4.2 inbound subscriptions (MOD-005 -> MOD-006,
    MOD-007 -> MOD-006) are ledgered telemetry seams.
    """
    for event_type, payload_model in (
        (EVENT_CASE_CONSULT_COMPLETE, CaseConsultCompletePayload),
        (EVENT_CASE_CLOSED, CaseClosedPayload),
        (EVENT_PRESCRIPTION_DRAFT_CREATED, PrescriptionDraftCreatedPayload),
        (EVENT_PRESCRIPTION_REVIEWED, PrescriptionReviewedPayload),
        (EVENT_PRESCRIPTION_APPROVED, PrescriptionApprovedPayload),
        (EVENT_PRESCRIPTION_REJECTED, PrescriptionRejectedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    registry.register(EVENT_PRE_SUMMARY_READY, _on_pre_summary_ready)
    registry.register(EVENT_PRE_SUMMARY_LOW_CONFIDENCE, _on_pre_summary_low_confidence)
    registry.register(EVENT_REPORT_FILED, _on_report_filed)


async def _on_pre_summary_ready(envelope: Envelope[BaseModel]) -> None:
    """Consume ``pre_summary.ready``: log the finalized pre-summary reaching care.

    This is the case-birth signal: a care case is born when its pre-summary is
    finalized (CONTEXT.md glossary). The spawn write is deferred - the producer
    payload carries no patient identity (``care_cases.patient_id`` is NOT NULL)
    - so this seam records the funnel fact only: ledger first (``run_handler``)
    so a replayed ``event_id`` is a no-op, then a structured, PHI-free log line
    with the process-local running count. Deliberately touches no domain table
    and emits no outbox row of its own (PHASE-8 T08 #424).
    """

    async def _impl(connection: AsyncConnection, payload: CarePreSummaryReadyPayload) -> None:
        del connection
        global _pre_summary_ready_count
        _pre_summary_ready_count += 1
        logger.info(
            "pre_summary.ready telemetry: intake_id=%s pre_summary_id=%s count=%s",
            payload.intake_id,
            payload.pre_summary_id,
            _pre_summary_ready_count,
        )

    await run_handler(
        envelope,
        CarePreSummaryReadyPayload,
        _impl,
        "pre_summary_ready_telemetry",
        CARE_SCHEMA,
    )


async def _on_pre_summary_low_confidence(envelope: Envelope[BaseModel]) -> None:
    """Consume ``pre_summary.low_confidence``: log the forced-review signal.

    The outset of the forced-review handshake gate (AMB-006, ADR-0001): a
    below-confidence pre-summary must be reviewed before the consult handshake.
    The gate itself already lives at ``CareFacade.mark_consult_complete`` via
    the finalized-pre-summary check; this subscription records the funnel fact
    that a low-confidence summary reached the care module. Ledger first
    (``run_handler``) so a replayed ``event_id`` is a no-op, then a structured,
    PHI-free log line with the process-local running count (PHASE-8 T08 #424).
    """

    async def _impl(
        connection: AsyncConnection, payload: CarePreSummaryLowConfidencePayload
    ) -> None:
        del connection
        global _pre_summary_low_confidence_count
        _pre_summary_low_confidence_count += 1
        logger.info(
            "pre_summary.low_confidence telemetry: intake_id=%s pre_summary_id=%s count=%s",
            payload.intake_id,
            payload.pre_summary_id,
            _pre_summary_low_confidence_count,
        )

    await run_handler(
        envelope,
        CarePreSummaryLowConfidencePayload,
        _impl,
        "pre_summary_low_confidence_telemetry",
        CARE_SCHEMA,
    )


async def _on_report_filed(envelope: Envelope[BaseModel]) -> None:
    """Consume ``report.filed``: log the report-filing fact for case context.

    Phase 9 (MOD-007) attachment seam: a filed report's case context (which
    visit, which clinician) is attached in that phase. Today MOD-003 already
    persists ``report.filed`` into the patient timeline; this subscription
    records the funnel fact that the filing reached the care module. Ledger
    first (``run_handler``) so a replayed ``event_id`` is a no-op, then a
    structured, PHI-free log line (order id only - never filename or patient)
    with the process-local running count (PHASE-8 T08 #424).
    """

    async def _impl(connection: AsyncConnection, payload: CareReportFiledPayload) -> None:
        del connection
        global _report_filed_count
        _report_filed_count += 1
        logger.info(
            "report.filed telemetry: order_id=%s count=%s",
            payload.order_id,
            _report_filed_count,
        )

    await run_handler(
        envelope,
        CareReportFiledPayload,
        _impl,
        "report_filed_telemetry",
        CARE_SCHEMA,
    )
